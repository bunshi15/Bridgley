# app/transport/http_app.py
"""
Production-ready HTTP application with security best practices.

Security layers:
1. Public: Only Twilio webhooks (with signature validation)
2. Protected: Admin endpoints (require admin token)
3. Dev-only: Development endpoints (only in dev environment)
4. No information leakage in production
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends, File, UploadFile, Form
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
# EPIC A1: Runtime-controlled handler registration (replaces static import).
from app.core.handlers.registry import register_handlers, parse_enabled_bots
from app.core.use_cases import Stage0Engine
from app.infra.pg_session_store_async import AsyncPostgresSessionStore
from app.infra.pg_lead_repo_async import AsyncPostgresLeadRepository
from app.infra.pg_inbound_repo_async import AsyncPostgresInboundMessageRepository
from app.infra.pg_uow_async import AsyncPostgresLeadFinalizer
from app.infra.db_async import close_pool, init_pool
from app.infra.schema_validator import validate_schema_version
from app.infra.logging_config import setup_logging, get_logger
from app.infra.rate_limiter import InMemoryRateLimiter, RateLimitDependency
from app.infra.metrics import get_metrics_collector
from app.infra.health_checks_async import get_async_health_checker
from app.transport.middleware import (
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    ErrorHandlingMiddleware,
)
from app.transport.security import (
    require_dev_environment,
    require_admin_auth,
    require_admin_host,
    require_metrics_auth,
    verify_media_signature,
    SecurityHeaders,
    sanitize_error_message,
)
from app.transport.twilio_webhook import twilio_webhook_handler
from app.transport.meta_webhook import meta_webhook_verify, meta_webhook_handler
from app.transport.telegram_webhook import telegram_webhook_handler

# Initialize logging first
setup_logging(
    level=settings.log_level,
    use_json=settings.is_production
)

logger = get_logger(__name__)


# ============================================================================
# DEPENDENCIES
# ============================================================================

def get_engine(request: Request) -> Stage0Engine:
    """Get engine from app state"""
    return request.app.state.engine


async def rate_limit_check(request: Request) -> None:
    """Rate limit dependency for protected endpoints"""
    limiter_dep = request.app.state.rate_limiter
    await limiter_dep(request)


# ============================================================================
# MIDDLEWARE FOR SECURITY HEADERS
# ============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        return SecurityHeaders.add_security_headers(response)


# ============================================================================
# TELEGRAM POLLER HELPERS (v0.8.1)
# ============================================================================

async def _start_telegram_pollers(engine: Stage0Engine) -> dict[str, "TelegramPoller"]:
    """
    Start Telegram long-polling loops for tenants that use polling mode.

    Scans the tenant registry for all tenants with a Telegram channel
    binding where ``config.channel_mode == "polling"``.  Creates and
    starts a ``TelegramPoller`` per tenant.

    Falls back to legacy single-tenant mode (settings.*) if no DB
    tenants use polling.

    Returns:
        dict mapping tenant_id → running TelegramPoller.
    """
    from app.transport.telegram_polling import TelegramPoller
    from app.infra.tenant_registry import get_all_tenants

    pollers: dict[str, TelegramPoller] = {}

    # Multi-tenant: scan registry
    for ctx in get_all_tenants():
        tg_binding = ctx.channels.get("telegram")
        if not tg_binding:
            continue
        if tg_binding.config.get("channel_mode") != "polling":
            continue
        if not tg_binding.credentials.get("bot_token"):
            logger.warning(
                f"Tenant {ctx.tenant_id} has Telegram polling but no bot_token — skipping"
            )
            continue

        poller = TelegramPoller(engine=engine, tenant_ctx=ctx)
        await poller.start()
        pollers[ctx.tenant_id] = poller

    # Legacy single-tenant fallback: if no DB tenants use polling,
    # check whether the global settings indicate polling mode.
    if not pollers:
        if (
            settings.channel_provider == "telegram"
            and settings.telegram_channel_mode == "polling"
        ):
            poller = TelegramPoller(engine=engine)
            await poller.start()
            pollers["__default__"] = poller

    if pollers:
        logger.info(
            f"Telegram pollers started: {list(pollers.keys())}"
        )

    return pollers


async def _sync_telegram_pollers(
    app_state,
    engine: Stage0Engine,
) -> dict[str, "TelegramPoller"]:
    """
    Reconcile running Telegram pollers with the current tenant registry.

    Called after ``reload_tenants()`` to start/stop pollers as needed.
    Uses a simple "stop-all, start-desired" strategy because reloads
    are rare (admin-triggered) and pollers reconnect quickly.

    Returns the new pollers dict (caller should assign to app.state).
    """
    from app.transport.telegram_polling import TelegramPoller

    old_pollers: dict[str, TelegramPoller] = getattr(
        app_state, "telegram_pollers", {}
    )

    # Stop all existing pollers
    for tid, poller in old_pollers.items():
        try:
            await poller.stop()
            logger.info(f"Telegram poller stopped during sync: tenant={tid}")
        except Exception as exc:
            logger.warning(f"Error stopping poller for tenant={tid}: {exc}")

    # Start fresh set based on current registry state
    new_pollers = await _start_telegram_pollers(engine)
    return new_pollers


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """Application lifecycle: startup and shutdown"""

    # STARTUP
    logger.info(
        f"Starting application: env={settings.app_env}, run_mode={settings.run_mode}"
    )

    # Initialize async database pool
    await init_pool()
    logger.info("Database pool initialized")

    # Validate production configuration
    if settings.is_production:
        missing = settings.validate_required_for_production()
        if missing:
            logger.critical(f"Missing required production settings: {missing}")
            raise RuntimeError(f"Missing production config: {missing}")

        # Additional production checks
        if not settings.admin_token or len(settings.admin_token) < 32:
            logger.critical("ADMIN_TOKEN must be at least 32 characters in production")
            raise RuntimeError("Weak ADMIN_TOKEN")

        if not settings.require_webhook_validation:
            logger.critical("REQUIRE_WEBHOOK_VALIDATION must be true in production")
            raise RuntimeError("Webhook validation disabled in production")

        if settings.log_level.upper() == "DEBUG":
            logger.critical("LOG_LEVEL=DEBUG is not allowed in production")
            raise RuntimeError("LOG_LEVEL=DEBUG in production")

    # SECURITY: Check token strength and warn about weak tokens
    from app.transport.security import check_configured_tokens
    check_configured_tokens()

    # Validate schema version (does NOT run migrations)
    # Migrations should be run separately: python -m app.infra.migrate
    try:
        schema_result = await validate_schema_version()
        logger.info(
            f"Schema validated: {schema_result['current_version']}",
            extra=schema_result
        )
    except Exception as exc:
        logger.critical(
            "Schema validation failed. Run migrations first: python -m app.infra.migrate",
            exc_info=True
        )
        raise

    # Initialize async repositories
    sessions = AsyncPostgresSessionStore()
    leads = AsyncPostgresLeadRepository()
    inbound = AsyncPostgresInboundMessageRepository()
    finalizer = AsyncPostgresLeadFinalizer()

    # Validate Meta config if selected
    if settings.channel_provider == "meta" and not settings.meta_enabled:
        logger.critical(
            "CHANNEL_PROVIDER=meta but Meta credentials are not configured. "
            "Set META_ACCESS_TOKEN, META_PHONE_NUMBER_ID, META_WEBHOOK_VERIFY_TOKEN."
        )
        raise RuntimeError("Meta Cloud API credentials not configured")

    # Validate Telegram config if selected
    if settings.channel_provider == "telegram" and not settings.telegram_channel_enabled:
        logger.critical(
            "CHANNEL_PROVIDER=telegram but Telegram bot token is not configured. "
            "Set TELEGRAM_CHANNEL_BOT_TOKEN or TELEGRAM_BOT_TOKEN."
        )
        raise RuntimeError("Telegram bot token not configured")

    # Create engine with selected provider
    provider = settings.channel_provider  # "twilio", "meta", or "telegram"
    logger.info(f"Channel provider: {provider}")

    fastapi_app.state.engine = Stage0Engine(
        tenant_id=settings.tenant_id,
        provider=provider,
        sessions=sessions,
        leads=leads,
        inbound=inbound,
        finalizer=finalizer,
    )

    # Initialize rate limiter
    rate_limiter = InMemoryRateLimiter(
        max_requests=settings.rate_limit_per_minute,
        window_seconds=60
    )
    fastapi_app.state.rate_limiter = RateLimitDependency(rate_limiter)

    # Log expected webhook URLs to simplify setup verification
    if settings.channel_provider == "twilio" and settings.twilio_webhook_url:
        logger.info(f"Twilio webhook URL: {settings.twilio_webhook_url}")
    if settings.channel_provider == "meta":
        # Meta webhook URL is relative — log a helpful hint
        logger.info("Meta webhook path: /webhooks/meta  (configure in Meta App Dashboard)")
        if settings.meta_phone_number_id:
            logger.info(f"Meta Phone Number ID: {settings.meta_phone_number_id}")

    # EPIC A1: Register bot handlers (runtime-controlled, replaces static import)
    registered_bots = register_handlers(parse_enabled_bots())
    logger.info("Registered bot handlers: %s", registered_bots)

    # Load tenant registry (v0.8 multi-tenant)
    from app.infra.tenant_registry import load_tenants
    tenant_count = await load_tenants()
    logger.info(f"Tenant registry loaded: {tenant_count} tenant(s)")

    # Telegram pollers: per-tenant registry (v0.8.1)
    # Only start in "all" or "poller" mode to prevent duplicate update consumption.
    telegram_pollers: dict[str, "TelegramPoller"] = {}
    if settings.run_mode in ("all", "poller"):
        from app.transport.telegram_polling import TelegramPoller
        telegram_pollers = await _start_telegram_pollers(fastapi_app.state.engine)
    else:
        logger.info(
            f"Telegram pollers skipped (run_mode={settings.run_mode})"
        )
    fastapi_app.state.telegram_pollers = telegram_pollers

    # Initialize job worker (v0.7 DB-backed queue)
    # Only start in "all" or "worker" mode to prevent duplicate processing.
    job_worker = None
    if settings.run_mode in ("all", "worker") and settings.job_worker_enabled:
        from app.infra.pg_job_repo_async import get_job_repo
        from app.infra.job_worker import (
            JobWorker,
            handle_outbound_reply,
            handle_process_media,
            handle_notify_operator,
            handle_media_cleanup,
        )
        from app.core.dispatch.jobs import handle_notify_crew_fallback

        job_repo = get_job_repo()
        job_worker = JobWorker(
            repo=job_repo,
            poll_interval=settings.job_worker_poll_interval,
            batch_size=settings.job_worker_batch_size,
            base_retry_delay=settings.job_worker_base_retry_delay,
            stale_timeout=settings.job_worker_stale_timeout,
        )

        # EPIC A2: Register job handlers based on WORKER_ROLE
        worker_role = settings.worker_role  # "core" | "dispatch" | "all"

        if worker_role in ("core", "all"):
            job_worker.register("outbound_reply", handle_outbound_reply)
            job_worker.register("process_media", handle_process_media)
            job_worker.register("notify_operator", handle_notify_operator)
            job_worker.register("media_cleanup", handle_media_cleanup)

        if worker_role in ("dispatch", "all"):
            job_worker.register("notify_crew_fallback", handle_notify_crew_fallback)

        logger.info("Job worker role=%s, handlers=%s", worker_role, job_worker.list_handlers())
        await job_worker.start()
    else:
        if settings.run_mode not in ("all", "worker"):
            logger.info(
                f"Job worker skipped (run_mode={settings.run_mode})"
            )
        elif not settings.job_worker_enabled:
            logger.info("Job worker skipped (job_worker_enabled=false)")

    # Log session management settings for diagnostics (Phase 7)
    logger.info(
        f"Session settings: ttl={settings.session_ttl_seconds}s, "
        f"stale_hint={settings.session_stale_hint_seconds}s"
    )

    logger.info("Application startup complete")

    yield

    # SHUTDOWN
    logger.info("Shutting down application")

    # Stop job worker if running
    if job_worker is not None:
        await job_worker.stop()

    # Stop all Telegram pollers
    for tid, poller in telegram_pollers.items():
        await poller.stop()

    # Close all shared HTTP sessions
    from app.infra.http_client import close_all_sessions
    await close_all_sessions()

    await close_pool()
    logger.info("Application shutdown complete")


# ============================================================================
# CREATE APP
# ============================================================================

app = FastAPI(
    title="Stage0 Bot",
    description="Production-ready conversational lead capture bot",
    version="1.0.0",
    lifespan=lifespan,
    # Security: Completely disable docs in production (None, not conditional URL)
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# CORS - Restrictive in production
# Note: This is an API server, not a browser app. CORS restrictions are for
# preventing unwanted browser-based access. Twilio/WhatsApp access the
# /media endpoint server-to-server, which bypasses CORS entirely.
if settings.is_production or settings.is_staging:
    app.add_middleware(
        CORSMiddleware,
        # Allow specific origins if admin UI is added later
        allow_origins=settings.allowed_origins if settings.allowed_origins != ["*"] else [],
        allow_credentials=False,
        # GET needed for /media and /health, POST for webhooks
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
else:
    # More permissive in dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add custom middleware
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestLoggingMiddleware, enabled=settings.enable_request_logging)
app.add_middleware(RequestIDMiddleware)


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with appropriate logging"""
    if exc.status_code >= 500:
        logger.error(f"Server error: {exc.detail}", extra={"status_code": exc.status_code})

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    logger.error(f"Unhandled exception: {exc.__class__.__name__}", exc_info=True)

    # Sanitize error message for production
    error_message = sanitize_error_message(exc, settings.is_production)

    return JSONResponse(
        status_code=500,
        content={"error": error_message},
    )


# ============================================================================
# PUBLIC ENDPOINTS (No authentication required)
# ============================================================================

@app.get("/health")
def health():
    """
    Basic health check - PUBLIC endpoint.
    Used by load balancers, monitoring, etc.
    Returns minimal information.
    """
    return {"status": "healthy"}


@app.get("/ready")
async def readiness():
    """
    Readiness check - PUBLIC endpoint.
    Kubernetes readiness probe.
    """
    health_checker = get_async_health_checker()
    result = await health_checker.run_checks(include_non_critical=False)

    if result["status"] == "unhealthy":
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy"}  # Minimal info
        )

    return {"status": "healthy"}


@app.post("/webhooks/twilio")
async def webhook_twilio(request: Request):
    """
    Twilio webhook endpoint - PUBLIC but VALIDATED.

    Security:
    - Signature validation required (HMAC-SHA1)
    - Rate limiting applied
    - Idempotency protection
    - No sensitive data in logs
    """
    return await twilio_webhook_handler(request)


@app.get("/webhooks/meta")
async def webhook_meta_verify(request: Request):
    """
    Meta WhatsApp Cloud API webhook verification - PUBLIC.

    Meta sends a GET request with hub.verify_token and hub.challenge
    to confirm webhook ownership.
    """
    return await meta_webhook_verify(request)


@app.post("/webhooks/meta")
async def webhook_meta(request: Request):
    """
    Meta WhatsApp Cloud API webhook events - PUBLIC but VALIDATED.

    Security:
    - Optional X-Hub-Signature-256 verification (if meta_app_secret configured)
    - Per-chat rate limiting
    - Idempotency protection via domain engine
    - Returns 200 quickly to avoid Meta timeouts
    """
    return await meta_webhook_handler(request)


@app.post("/webhooks/telegram")
async def webhook_telegram(request: Request):
    """
    Telegram Bot API webhook endpoint - PUBLIC but VALIDATED.

    Security:
    - X-Telegram-Bot-Api-Secret-Token validation (if configured)
    - Per-chat rate limiting
    - Idempotency protection via domain engine
    - Returns 200 quickly to avoid Telegram timeouts
    """
    return await telegram_webhook_handler(request)


# ============================================================================
# TENANT-PREFIXED WEBHOOK ENDPOINTS (v0.8 Multi-Tenant)
# ============================================================================

# The single app.state.engine is shared across all tenants.
# Engine is purely orchestrational (holds shared repo refs, NOT credentials).
# Tenant-specific credentials are resolved per-request from the tenant registry.


async def _resolve_tenant(tenant_id: str) -> "TenantContext":
    """Resolve tenant from registry, raise 404 if not found or inactive."""
    from app.infra.tenant_registry import get_tenant

    ctx = get_tenant(tenant_id)
    if ctx is None or not ctx.is_active:
        raise HTTPException(status_code=404, detail="Not found")
    return ctx


@app.post("/t/{tenant_id}/webhooks/twilio")
async def webhook_twilio_tenant(tenant_id: str, request: Request):
    """Tenant-prefixed Twilio webhook."""
    ctx = await _resolve_tenant(tenant_id)
    return await twilio_webhook_handler(request, tenant_ctx=ctx, engine_override=request.app.state.engine)


@app.get("/t/{tenant_id}/webhooks/meta")
async def webhook_meta_verify_tenant(tenant_id: str, request: Request):
    """Tenant-prefixed Meta webhook verification."""
    ctx = await _resolve_tenant(tenant_id)
    return await meta_webhook_verify(request, tenant_ctx=ctx)


@app.post("/t/{tenant_id}/webhooks/meta")
async def webhook_meta_tenant(tenant_id: str, request: Request):
    """Tenant-prefixed Meta webhook."""
    ctx = await _resolve_tenant(tenant_id)
    return await meta_webhook_handler(request, tenant_ctx=ctx, engine_override=request.app.state.engine)


@app.post("/t/{tenant_id}/webhooks/telegram")
async def webhook_telegram_tenant(tenant_id: str, request: Request):
    """Tenant-prefixed Telegram webhook."""
    ctx = await _resolve_tenant(tenant_id)
    return await telegram_webhook_handler(request, tenant_ctx=ctx, engine_override=request.app.state.engine)


def _validate_s3_redirect_url(url: str) -> bool:
    """
    SECURITY: Validate S3 URL before redirecting to prevent open redirect attacks.

    Only allows redirects to:
    1. Configured S3_PUBLIC_URL prefix
    2. Configured S3_ENDPOINT_URL prefix
    3. Same host as S3_ENDPOINT_URL (any port) - for internal MinIO migrations
    """
    if not url:
        return False

    from urllib.parse import urlparse

    # Check against configured S3 URLs
    allowed_prefixes = []

    if settings.s3_public_url:
        allowed_prefixes.append(settings.s3_public_url.rstrip('/'))

    if settings.s3_endpoint_url:
        allowed_prefixes.append(settings.s3_endpoint_url.rstrip('/'))

    for prefix in allowed_prefixes:
        if url.startswith(prefix):
            return True

    # For internal MinIO: also allow same hostname with different port
    # This handles cases where MinIO port was changed after photos were stored
    if settings.s3_endpoint_url:
        try:
            endpoint_parsed = urlparse(settings.s3_endpoint_url)
            url_parsed = urlparse(url)

            # Allow same scheme + host, any port (for internal services only)
            # Only for http (internal), not https (public)
            if (url_parsed.scheme == "http" and
                endpoint_parsed.scheme == "http" and
                url_parsed.hostname == endpoint_parsed.hostname):
                logger.debug(f"Allowing internal MinIO URL with different port: {url[:50]}")
                return True
        except Exception:
            pass

    logger.warning(f"Blocked redirect to untrusted URL: {url[:100]}")
    return False


@app.get("/media/{photo_id}", dependencies=[Depends(rate_limit_check)])
async def get_photo(photo_id: str, request: Request):
    """
    Serve a photo by ID — signed URL required in production/staging.

    Security:
    - HMAC-signed URLs with expiration (production/staging)
    - UUID validation prevents path traversal
    - Redirect URL validation prevents open redirect attacks
    - Rate limiting via global limiter
    - Cache headers for CDN efficiency

    URL format:
      /media/{photo_id}?sig=<HMAC>&exp=<unix_timestamp>

    In dev mode, unsigned access is allowed for convenience.

    Storage Modes:

    1. PRODUCTION (cloud bucket with public URL):
       - Set S3_PUBLIC_URL to your CDN/bucket public URL
       - Photos redirect to public S3 URL (fast, CDN-ready)
       - Example: S3_PUBLIC_URL=https://cdn.example.com/bucket

    2. TESTING (internal MinIO without public URL):
       - Leave S3_PUBLIC_URL empty
       - Photos are proxied through this endpoint using authenticated S3 client
       - App must be publicly accessible for Telegram/WhatsApp to fetch

    3. LEGACY (database storage):
       - If S3 not configured, photos served directly from DB
       - Not recommended for production (large binary data in DB)
    """
    from uuid import UUID
    from fastapi.responses import Response, RedirectResponse
    from app.infra.pg_photo_repo_async import get_photo_repo

    # SECURITY: Require signed URL in production/staging
    if settings.is_production or settings.is_staging:
        sig = request.query_params.get("sig")
        exp = request.query_params.get("exp")

        if not sig or not exp:
            logger.warning(f"Media access denied: missing signature params, photo_id={photo_id[:8]}")
            raise HTTPException(status_code=403, detail="Forbidden")

        is_valid, error = verify_media_signature(photo_id, sig, exp)
        if not is_valid:
            logger.warning(f"Media access denied: {error}, photo_id={photo_id[:8]}")
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        uuid_id = UUID(photo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid photo ID")

    repo = get_photo_repo()
    photo = await repo.get_by_id(uuid_id)

    if not photo:
        # EPIC G: Fall back to media_assets table (videos, generic media)
        from app.infra.pg_media_asset_repo_async import get_media_asset_repo
        from app.infra.s3_storage import get_s3_storage, is_s3_available

        asset_repo = get_media_asset_repo()
        asset = await asset_repo.get_by_id(uuid_id)

        if not asset:
            raise HTTPException(status_code=404, detail="Media not found")

        # Media assets are always in S3 — generate presigned redirect
        if not is_s3_available():
            logger.error("S3 not available for media asset: %s", str(asset.id)[:8])
            raise HTTPException(status_code=502, detail="Storage not configured")

        try:
            s3 = get_s3_storage()
            presigned_url = await s3.generate_presigned_get_url(asset.s3_key, expires_seconds=1800)

            # G4.3: log only truncated asset_id, never full URL
            logger.info("Media asset served via presigned URL: asset=%s", str(asset.id)[:8])

            return RedirectResponse(
                url=presigned_url,
                status_code=302,
                headers={"Cache-Control": "private, max-age=300"},
            )
        except Exception as e:
            logger.error("Failed to generate presigned URL: asset=%s, error=%s", str(asset.id)[:8], e)
            raise HTTPException(status_code=502, detail="Storage unavailable")

    # ----- Existing photo serving logic (backward compatible) -----

    # If stored in S3
    if photo.s3_url:
        # SECURITY: Validate redirect URL to prevent open redirect attacks
        if settings.s3_public_url and _validate_s3_redirect_url(photo.s3_url):
            return RedirectResponse(
                url=photo.s3_url,
                status_code=302,
                headers={"Cache-Control": "public, max-age=31536000"},
            )
        else:
            # S3 is internal (MinIO) - download using authenticated S3 client
            from app.infra.s3_storage import get_s3_storage, is_s3_available

            if not is_s3_available():
                logger.error(f"S3 not available for photo proxy: {photo.id}")
                raise HTTPException(status_code=502, detail="Storage not configured")

            try:
                # Extract extension from stored URL or filename
                ext = "jpg"
                if photo.filename:
                    ext = photo.filename.rsplit(".", 1)[-1] if "." in photo.filename else "jpg"

                s3 = get_s3_storage()
                content = await s3.download(photo.tenant_id, str(photo.id), ext)

                if content is None:
                    logger.error(f"Photo not found in S3: {photo.id}")
                    raise HTTPException(status_code=404, detail="Photo not found in storage")

                return Response(
                    content=content,
                    media_type=photo.content_type or "image/jpeg",
                    headers={
                        "Content-Disposition": f"inline; filename={photo.filename}",
                        "Cache-Control": "public, max-age=31536000",
                    }
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to download photo from S3: {e}", exc_info=True)
                raise HTTPException(status_code=502, detail="Storage unavailable")

    # Serve from database
    if not photo.data:
        raise HTTPException(status_code=404, detail="Photo data not found")

    return Response(
        content=photo.data,
        media_type=photo.content_type,
        headers={
            "Content-Disposition": f"inline; filename={photo.filename}",
            "Cache-Control": "public, max-age=31536000",  # Cache for 1 year (immutable)
        }
    )


# ============================================================================
# MONITORING ENDPOINTS (Internal network or METRICS_TOKEN)
# Access control:
#   - If METRICS_TOKEN is set: require Bearer token
#   - If METRICS_TOKEN is not set: require internal network (RFC1918/localhost)
# ============================================================================

@app.get("/health/detailed", dependencies=[Depends(require_metrics_auth)])
async def detailed_health():
    """
    Detailed health check - INTERNAL/METRICS only.
    Returns sensitive information about system state.

    Access: Internal network OR METRICS_TOKEN
    """
    health_checker = get_async_health_checker()
    return await health_checker.run_checks(include_non_critical=True)


@app.get("/metrics", dependencies=[Depends(require_metrics_auth)])
def metrics():
    """
    Metrics endpoint - INTERNAL/METRICS only.
    Exposes operational metrics for Prometheus/monitoring.

    Access: Internal network OR METRICS_TOKEN
    """
    collector = get_metrics_collector()
    return collector.get_metrics()


# ============================================================================
# ADMIN ENDPOINTS (Require admin token + admin host in production)
# In production with ADMIN_HOST configured:
#   - bot.example.com -> returns 404 for admin endpoints
#   - bot-admin.example.com -> admin endpoints accessible
# ============================================================================


@app.post("/admin/cleanup", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_cleanup(engine: Stage0Engine = Depends(get_engine)):
    """
    Manual session cleanup - ADMIN only.
    Also prunes stale idempotency records (> 30 days).
    """
    logger.info(f"Manual cleanup triggered: ttl={settings.session_ttl_seconds}s")
    result = await engine.cleanup_expired(settings.session_ttl_seconds)

    # Prune old inbound idempotency records to prevent unbounded growth
    try:
        from app.infra.pg_inbound_repo_async import AsyncPostgresInboundMessageRepository
        inbound_repo = AsyncPostgresInboundMessageRepository()
        inbound_deleted = await inbound_repo.cleanup_old(ttl_days=30)
        result["deleted_inbound_old"] = inbound_deleted
    except Exception as exc:
        logger.warning(f"Inbound cleanup failed (non-critical): {exc}")
        result["deleted_inbound_old"] = "error"

    return result


@app.post("/admin/metrics/reset", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
def admin_reset_metrics():
    """
    Reset metrics - ADMIN only.
    Use with caution.
    """
    logger.warning("Metrics reset triggered")
    collector = get_metrics_collector()
    collector.reset()
    return {"ok": True, "message": "Metrics reset"}


@app.post("/admin/chat/reset", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_soft_reset(payload: dict, engine: Stage0Engine = Depends(get_engine)):
    """
    Soft reset chat session - ADMIN only.
    Resets session state but preserves lead data and message history.
    Useful for allowing user to restart conversation without data loss.
    """
    chat_id = payload.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
    logger.info(f"Admin soft reset: chat={chat_id[:6]}***")
    return await engine.soft_reset_chat(chat_id)


@app.get("/admin/queue/status", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_queue_status():
    """
    Outbound message queue status - ADMIN only.
    Shows queue size and configuration for monitoring.
    """
    from app.infra.outbound_queue import get_outbound_queue

    queue = get_outbound_queue()
    return {
        "queue_size": queue.queue_size,
        "config": {
            "messages_per_second": settings.outbound_messages_per_second,
            "max_retries": settings.outbound_max_retries,
            "base_retry_delay": settings.outbound_base_retry_delay,
        }
    }


@app.post("/admin/queue/flush", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_queue_flush():
    """
    Flush outbound message queue - ADMIN only.
    Forces processing of all queued messages.
    """
    from app.infra.outbound_queue import get_outbound_queue

    queue = get_outbound_queue()
    initial_size = queue.queue_size
    logger.info(f"Admin queue flush: {initial_size} messages")

    await queue.flush()

    return {
        "flushed": initial_size,
        "remaining": queue.queue_size,
    }


@app.get("/admin/jobs", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_jobs_status(
    status: str | None = None,
    limit: int = 50,
):
    """
    Job queue status — ADMIN only.
    Returns counts by status and recent jobs.
    """
    from app.infra.pg_job_repo_async import get_job_repo

    repo = get_job_repo()
    counts = await repo.count_by_status()
    recent = await repo.get_recent(limit=limit, status=status)

    return {
        "counts": counts,
        "recent": [
            {
                "id": j.id,
                "type": j.job_type,
                "status": j.status,
                "attempts": j.attempts,
                "max_attempts": j.max_attempts,
                "error": j.error_message,
                "created_at": j.created_at.isoformat(),
                "scheduled_at": j.scheduled_at.isoformat(),
            }
            for j in recent
        ],
    }


@app.post("/admin/jobs/cleanup", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_jobs_cleanup():
    """
    Purge old completed/failed jobs and reset stale running jobs — ADMIN only.
    """
    from app.infra.pg_job_repo_async import get_job_repo

    repo = get_job_repo()
    completed = await repo.cleanup_completed(ttl_days=settings.job_cleanup_completed_ttl_days)
    failed = await repo.cleanup_failed(ttl_days=settings.job_cleanup_failed_ttl_days)
    stale = await repo.reset_stale_running(timeout_seconds=settings.job_worker_stale_timeout)

    return {
        "deleted_completed": completed,
        "deleted_failed": failed,
        "reset_stale": stale,
    }


@app.post("/admin/media/cleanup", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_media_cleanup():
    """
    Trigger media TTL cleanup — ADMIN only (EPIC G2.2).
    Deletes expired media assets from S3 and database.
    """
    from app.infra.pg_media_asset_repo_async import get_media_asset_repo
    from app.infra.s3_storage import get_s3_storage, is_s3_available

    repo = get_media_asset_repo()
    expired = await repo.delete_expired(batch_size=200)

    s3_deleted = 0
    s3_errors = 0

    if expired and is_s3_available():
        s3 = get_s3_storage()
        for record in expired:
            try:
                await s3.delete_object(record.s3_key)
                s3_deleted += 1
            except Exception:
                s3_errors += 1

    return {
        "expired_deleted": len(expired),
        "s3_deleted": s3_deleted,
        "s3_errors": s3_errors,
    }


# ============================================================================
# ADMIN TENANT ENDPOINTS (v0.8 Multi-Tenant)
#
# Thin transport layer — all business logic lives in AdminApplicationService.
# Routes: parse request → call service → map AdminError → return JSON.
# ============================================================================

from app.admin.service import get_admin_service
from app.admin.errors import AdminError
from app.admin.models import CreateTenantRequest, UpdateTenantRequest, UpsertChannelRequest
from pydantic import ValidationError as PydanticValidationError


@app.get("/admin/tenants", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_list_tenants():
    """List all tenants (minimal fields, no secrets, no raw config)."""
    svc = get_admin_service()
    summaries = await svc.list_tenants()
    return {"tenants": [s.model_dump() for s in summaries]}


@app.post("/admin/tenants", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_create_tenant(payload: dict):
    """Create a new tenant."""
    try:
        req = CreateTenantRequest(**payload)
    except PydanticValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    svc = get_admin_service()
    try:
        result = await svc.create_tenant(req)
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return result.model_dump(exclude_none=True)


@app.get("/admin/tenants/{tid}", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_get_tenant(tid: str):
    """Get a single tenant with channel bindings (credentials hidden, config redacted)."""
    svc = get_admin_service()
    try:
        detail = await svc.get_tenant(tid)
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return detail.model_dump()


@app.put("/admin/tenants/{tid}", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_update_tenant(tid: str, payload: dict):
    """Update a tenant."""
    try:
        req = UpdateTenantRequest(**payload)
    except PydanticValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    svc = get_admin_service()
    try:
        result = await svc.update_tenant(tid, req)
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return result.model_dump(exclude_none=True)


@app.post("/admin/tenants/{tid}/channels", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_upsert_channel(tid: str, payload: dict):
    """Add or update a channel binding for a tenant."""
    try:
        req = UpsertChannelRequest(**payload)
    except PydanticValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    svc = get_admin_service()
    try:
        result = await svc.upsert_channel(tid, req)
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return result.model_dump(exclude_none=True)


@app.delete(
    "/admin/tenants/{tid}/channels/{provider}",
    dependencies=[Depends(require_admin_host), Depends(require_admin_auth)],
)
async def admin_delete_channel(tid: str, provider: str):
    """Remove a channel binding from a tenant."""
    svc = get_admin_service()
    try:
        result = await svc.delete_channel(tid, provider)
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return result.model_dump(exclude_none=True)


@app.post("/admin/tenants/reload", dependencies=[Depends(require_admin_host), Depends(require_admin_auth)])
async def admin_reload_tenants(request: Request):
    """Refresh in-memory tenant cache from DB and sync Telegram pollers."""
    svc = get_admin_service()
    try:
        result = await svc.reload_tenant_registry()
    except AdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    # Sync Telegram pollers to match updated tenant registry (v0.8.1)
    try:
        new_pollers = await _sync_telegram_pollers(
            request.app.state,
            request.app.state.engine,
        )
        request.app.state.telegram_pollers = new_pollers
        logger.info(f"Telegram pollers synced after reload: {list(new_pollers.keys())}")
    except Exception as exc:
        logger.error(f"Telegram poller sync failed after reload: {exc}", exc_info=True)

    return result.model_dump(exclude_none=True)


# ============================================================================
# DEV-ONLY ENDPOINTS (Only available in dev environment)
# ============================================================================

@app.get("/", include_in_schema=False)
def root_public():
    """
    Public root - minimal HTML page confirming the service is running.
    No sensitive information exposed.
    """
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Bridgley</title></head><body>"
        "<h3>Bridgley</h3><p>Service is running.</p>"
        "</body></html>"
    )


@app.get("/__dev/info", dependencies=[Depends(require_dev_environment())], include_in_schema=False)
def dev_info():
    """
    Development service info - DEV ONLY.
    Returns 404 in production (endpoint hidden).
    """
    return {
        "service": "Stage0 Bot",
        "version": "1.0.0",
        "environment": settings.app_env,
        "tenant": settings.tenant_id,
        "channel_provider": settings.channel_provider,
        "endpoints": {
            "health": "/health",
            "readiness": "/ready",
            "webhook_twilio": "/webhooks/twilio",
            "webhook_meta": "/webhooks/meta",
            "webhook_telegram": "/webhooks/telegram",
        }
    }


@app.post(
    "/dev/chat",
    dependencies=[Depends(require_dev_environment()), Depends(rate_limit_check)]
)
async def dev_chat(payload: dict, engine: Stage0Engine = Depends(get_engine)):
    """
    Development chat endpoint - DEV ONLY.
    For testing without Twilio.
    """
    from app.transport.adapters import DevAdapter

    adapter = DevAdapter()
    message = adapter.adapt(
        tenant_id=settings.tenant_id,
        chat_id=payload.get("chat_id"),
        text=payload.get("text"),
        message_id=payload.get("message_id"),
    )

    result = await engine.process_inbound_message(message)
    return result


@app.post(
    "/dev/media",
    dependencies=[Depends(require_dev_environment()), Depends(rate_limit_check)]
)
async def dev_media(payload: dict, engine: Stage0Engine = Depends(get_engine)):
    """
    Development media endpoint - DEV ONLY.
    """
    from app.transport.adapters import DevAdapter

    adapter = DevAdapter()
    message = adapter.adapt(
        tenant_id=settings.tenant_id,
        chat_id=payload.get("chat_id"),
        message_id=payload.get("message_id"),
        media_url=payload.get("media_url"),
    )

    result = await engine.process_inbound_message(message)
    return result


@app.post(
    "/dev/photo",
    dependencies=[Depends(require_dev_environment()), Depends(rate_limit_check)]
)
async def dev_photo(
    request: Request,
    chat_id: str = Form(...),
    message_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    engine: Stage0Engine = Depends(get_engine),
):
    """
    Development photo upload endpoint - DEV ONLY.

    Security features:
    - File size validation (max 10MB)
    - Format validation (magic bytes)
    - Image re-encoding (strips EXIF/metadata)
    - Dimension limits
    - UUID filename generation
    """
    from app.infra.media_service import get_media_service
    from app.infra.image_processor import ImageError

    # Read file data
    data = await file.read()

    # Validate and process image securely
    try:
        media_service = get_media_service()
        processed = media_service.process_upload(data)

        logger.info(
            f"Dev photo uploaded: chat={chat_id[:6]}***, "
            f"uuid={processed.uuid}, size={processed.size_bytes}, "
            f"dimensions={processed.width}x{processed.height}"
        )

        # Save the processed image to database
        photo_id = await media_service.save_processed_image(processed, settings.tenant_id, chat_id)

    except ImageError as e:
        logger.warning(f"Photo upload rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # Process as media message
    result = await engine.process_media(
        chat_id=chat_id,
        message_id=message_id,
    )

    return {
        **result,
        "media": {
            "photo_id": photo_id,
            "uuid": processed.uuid,
            "filename": processed.filename,
            "size_bytes": processed.size_bytes,
            "width": processed.width,
            "height": processed.height,
        }
    }


@app.post("/dev/reset", dependencies=[Depends(require_dev_environment())])
async def dev_reset(payload: dict, engine: Stage0Engine = Depends(get_engine)):
    """
    Reset chat session - DEV ONLY.
    Accepts JSON body with chat_id.
    """
    chat_id = payload.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
    logger.info(f"Resetting chat: {chat_id[:6]}***")
    return await engine.reset_chat(chat_id)


# ============================================================================
# CATCH-ALL (Return 404 for unknown routes)
# ============================================================================

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(path: str):
    """
    Catch-all route for undefined endpoints.
    Returns generic 404 without revealing information.
    """
    logger.warning(f"404 - Unknown route accessed: {path}")
    raise HTTPException(status_code=404, detail="Not found")


# ============================================================================
# STARTUP VALIDATION
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Production-ready uvicorn settings
    uvicorn.run(
        "app.transport.http_app:app",
        host="0.0.0.0",
        port=8099,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
        access_log=not settings.is_production,  # Disable in prod (use middleware logging)
        server_header=False,  # Don't expose server version
        date_header=False,  # Don't expose server time
    )
