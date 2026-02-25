# app/transport/security.py
"""
Security utilities for production-ready API.
Implements defense-in-depth with multiple security layers.

Security features:
- Constant-time token comparison (timing attack prevention)
- Token entropy validation (weak token detection)
- Authorization header sanitization (prevents token logging)
- HMAC request signing (secret never sent over wire)
- Internal network validation
- Rate limiting by key
"""
import hmac
import ipaddress
import secrets
import hashlib
import time
from functools import lru_cache, wraps
from typing import Callable

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# Minimum token length for security (32 bytes = 256 bits)
MIN_TOKEN_LENGTH = 32
# Minimum entropy check - reject obviously weak tokens
WEAK_TOKEN_PATTERNS = [
    "password", "secret", "token", "admin", "test", "demo",
    "123456", "000000", "111111", "aaaaaa",
]

# Security scheme for OpenAPI docs - shows "Authorize" button
bearer_scheme = HTTPBearer(
    scheme_name="Admin Token",
    description="Enter your admin token (without 'Bearer ' prefix)",
    auto_error=False,  # We handle errors ourselves for better messages
)


class SecurityError(HTTPException):
    """Base security exception"""
    pass


def validate_token_strength(token: str, token_name: str = "token") -> list[str]:
    """
    Validate that a token meets minimum security requirements.
    Returns list of warnings (empty if token is strong).

    SECURITY: Call this at startup to warn about weak tokens.

    Checks:
    - Minimum length (32 chars)
    - Not a common weak pattern
    - Has reasonable entropy (mix of characters)
    """
    warnings = []

    if len(token) < MIN_TOKEN_LENGTH:
        warnings.append(
            f"{token_name} is too short ({len(token)} chars). "
            f"Minimum recommended: {MIN_TOKEN_LENGTH} chars"
        )

    token_lower = token.lower()
    for pattern in WEAK_TOKEN_PATTERNS:
        if pattern in token_lower:
            warnings.append(
                f"{token_name} contains weak pattern '{pattern}'. "
                "Use a cryptographically random token"
            )
            break

    # Check character diversity (should have letters, numbers, ideally symbols)
    has_upper = any(c.isupper() for c in token)
    has_lower = any(c.islower() for c in token)
    has_digit = any(c.isdigit() for c in token)

    if not (has_upper and has_lower and has_digit):
        warnings.append(
            f"{token_name} has low character diversity. "
            "Recommended: mix of uppercase, lowercase, and numbers"
        )

    return warnings


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.
    Use this to generate ADMIN_TOKEN and METRICS_TOKEN values.

    Returns URL-safe base64 string (letters, numbers, -, _)
    """
    return secrets.token_urlsafe(length)


def check_configured_tokens():
    """
    Check configured tokens at startup and log warnings for weak tokens.
    Call this from app startup.
    """
    if settings.admin_token:
        warnings = validate_token_strength(settings.admin_token, "ADMIN_TOKEN")
        for warning in warnings:
            logger.warning(f"SECURITY: {warning}")

    if settings.metrics_token:
        warnings = validate_token_strength(settings.metrics_token, "METRICS_TOKEN")
        for warning in warnings:
            logger.warning(f"SECURITY: {warning}")


# =============================================================================
# HMAC Request Signing (Alternative to Bearer Token)
# =============================================================================
# The secret never travels over the wire - instead, requests are signed.
# Similar to AWS Signature V4, Stripe webhooks, etc.
#
# Client sends:
#   X-Timestamp: 1699999999
#   X-Signature: HMAC-SHA256(secret, timestamp + method + path + body)
#
# Benefits:
#   - Secret never exposed in transit (even with TLS interception)
#   - Replay protection via timestamp
#   - Request integrity verification
# =============================================================================

# Maximum age for signed requests (prevents replay attacks)
HMAC_MAX_AGE_SECONDS = 300  # 5 minutes


def compute_request_signature(
    secret: str,
    timestamp: str,
    method: str,
    path: str,
    body: bytes = b"",
) -> str:
    """
    Compute HMAC-SHA256 signature for a request.

    Args:
        secret: The shared secret (ADMIN_TOKEN)
        timestamp: Unix timestamp as string
        method: HTTP method (GET, POST, etc.)
        path: Request path (e.g., /admin/sessions/cleanup)
        body: Request body bytes (empty for GET)

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    # Create signing string: timestamp.method.path.body_hash
    body_hash = hashlib.sha256(body).hexdigest()
    signing_string = f"{timestamp}.{method.upper()}.{path}.{body_hash}"

    signature = hmac.new(
        secret.encode(),
        signing_string.encode(),
        hashlib.sha256
    ).hexdigest()

    return signature


def verify_request_signature(
    secret: str,
    timestamp: str,
    signature: str,
    method: str,
    path: str,
    body: bytes = b"",
) -> tuple[bool, str | None]:
    """
    Verify HMAC request signature.

    Returns:
        (is_valid, error_message)
    """
    # Check timestamp freshness (replay protection)
    try:
        request_time = int(timestamp)
    except ValueError:
        return False, "Invalid timestamp format"

    current_time = int(time.time())
    age = abs(current_time - request_time)

    if age > HMAC_MAX_AGE_SECONDS:
        return False, f"Request expired (age: {age}s, max: {HMAC_MAX_AGE_SECONDS}s)"

    # Compute expected signature
    expected = compute_request_signature(secret, timestamp, method, path, body)

    # Constant-time comparison
    if not hmac.compare_digest(signature, expected):
        return False, "Invalid signature"

    return True, None


async def require_admin_hmac(request: Request):
    """
    Dependency that requires HMAC-signed requests for admin endpoints.

    Headers required:
        X-Timestamp: Unix timestamp (seconds)
        X-Signature: HMAC-SHA256 signature

    Example with curl:
        TIMESTAMP=$(date +%s)
        BODY=""
        SIGNATURE=$(echo -n "$TIMESTAMP.GET./admin/sessions/cleanup.$(echo -n "$BODY" | sha256sum | cut -d' ' -f1)" | \
                    openssl dgst -sha256 -hmac "$ADMIN_TOKEN" | cut -d' ' -f2)
        curl -H "X-Timestamp: $TIMESTAMP" -H "X-Signature: $SIGNATURE" http://localhost:8099/admin/sessions/cleanup

    Or use the helper script: python scripts/sign_request.py
    """
    if not settings.admin_token:
        logger.critical("ADMIN_TOKEN not configured but HMAC endpoint accessed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable"
        )

    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not timestamp or not signature:
        logger.warning("HMAC endpoint accessed without signature headers")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Timestamp or X-Signature headers"
        )

    # Get request body for POST/PUT/PATCH
    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    # Verify signature
    is_valid, error = verify_request_signature(
        secret=settings.admin_token,
        timestamp=timestamp,
        signature=signature,
        method=request.method,
        path=request.url.path,
        body=body,
    )

    if not is_valid:
        logger.warning(
            f"Invalid HMAC signature: {error}",
            extra={"path": request.url.path, "method": request.method}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

    logger.debug(f"HMAC auth successful for {request.method} {request.url.path}")


def require_dev_environment():
    """
    Dependency that only allows access in dev environment.
    Use for endpoints that should NEVER be exposed in production or staging.
    """
    def dependency():
        if settings.app_env != "dev":
            logger.warning(
                "Attempted access to dev-only endpoint in non-dev environment",
                extra={"env": settings.app_env}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found"  # Don't reveal endpoint exists
            )
    return dependency


def require_admin_host(request: Request):
    """
    Dependency that only allows access from admin host in production.

    In production:
      - If admin_host is configured, only requests to that host are allowed
      - Requests to public host get 404 (endpoint hidden)

    In dev: All hosts allowed

    Example:
      Production setup:
        - bot.example.com -> public endpoints (webhook, health)
        - bot-admin.example.com -> admin endpoints (metrics, cleanup, reset)

      Configure: ADMIN_HOST=bot-admin.example.com
    """
    if not settings.is_production:
        return  # Allow all in dev

    if not settings.admin_host:
        return  # No host restriction configured

    # Get the host from request
    request_host = request.headers.get("host", "").split(":")[0]  # Remove port

    if request_host != settings.admin_host:
        logger.warning(
            f"Admin endpoint accessed from wrong host: {request_host}",
            extra={"request_host": request_host, "admin_host": settings.admin_host}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found"  # Don't reveal endpoint exists
        )


def _verify_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> tuple[bool, str | None]:
    """Verify Bearer token. Returns (is_valid, error_message)."""
    if not credentials:
        return False, "Missing Authorization header"

    if not hmac.compare_digest(credentials.credentials, settings.admin_token):
        return False, "Invalid token"

    return True, None


async def _verify_hmac_signature(request: Request) -> tuple[bool, str | None]:
    """Verify HMAC signature. Returns (is_valid, error_message)."""
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not timestamp or not signature:
        return False, "Missing X-Timestamp or X-Signature headers"

    # Get request body for POST/PUT/PATCH
    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    return verify_request_signature(
        secret=settings.admin_token,
        timestamp=timestamp,
        signature=signature,
        method=request.method,
        path=request.url.path,
        body=body,
    )


async def require_admin_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """
    Unified admin authentication supporting Bearer token and/or HMAC signing.

    Mode is controlled by ADMIN_AUTH_MODE setting:
    - "bearer": Only accept Bearer token (simpler, token sent in header)
    - "hmac": Only accept HMAC-signed requests (more secure, secret never sent)
    - "both": Accept either method (default, good for migration)

    HMAC Signing (recommended for production):
        Secret never leaves your machine - only signature is sent.
        Headers: X-Timestamp + X-Signature
        Use: python scripts/sign_request.py GET /admin/endpoint --curl

    Bearer Token (simpler):
        Header: Authorization: Bearer <token>
        Use: curl -H "Authorization: Bearer $ADMIN_TOKEN" http://host/endpoint

    Usage:
        @app.get("/admin/endpoint", dependencies=[Depends(require_admin_auth)])
        async def admin_endpoint():
            ...
    """
    if not settings.admin_token:
        logger.critical("ADMIN_TOKEN not configured but admin endpoint accessed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable"
        )

    auth_mode = settings.admin_auth_mode
    bearer_valid, bearer_error = False, None
    hmac_valid, hmac_error = False, None

    # Try Bearer auth
    if auth_mode in ("bearer", "both"):
        bearer_valid, bearer_error = _verify_bearer_token(credentials)
        if bearer_valid:
            logger.debug(f"Bearer auth successful for {request.method} {request.url.path}")
            return

    # Try HMAC auth
    if auth_mode in ("hmac", "both"):
        hmac_valid, hmac_error = await _verify_hmac_signature(request)
        if hmac_valid:
            logger.debug(f"HMAC auth successful for {request.method} {request.url.path}")
            return

    # Both failed - log and return appropriate error
    if auth_mode == "bearer":
        logger.warning(f"Bearer auth failed: {bearer_error}", extra={"path": request.url.path})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif auth_mode == "hmac":
        logger.warning(f"HMAC auth failed: {hmac_error}", extra={"path": request.url.path})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing signature"
        )
    else:  # both
        logger.warning(
            f"All auth methods failed: bearer={bearer_error}, hmac={hmac_error}",
            extra={"path": request.url.path}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Bearer token or HMAC signature)",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Legacy alias for backwards compatibility
def require_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """
    DEPRECATED: Use require_admin_auth instead for HMAC support.

    Dependency that requires valid admin token via Authorization Bearer header.
    Use for admin/management endpoints.

    SECURITY CRITICAL:
    - Token MUST be passed as Authorization Bearer header (standard OAuth2 scheme)
    - Query params leak in logs, browser history, and proxy logs
    - Constant-time comparison prevents timing attacks
    - Logs unauthorized attempts
    - Generic error messages prevent enumeration

    Usage:
        @app.get("/admin/endpoint", dependencies=[Depends(require_admin_token)])
        async def admin_endpoint():
            ...

    Client example:
        curl -H "Authorization: Bearer your-secret-token" http://localhost:8099/admin/endpoint
    """
    if not settings.admin_token:
        logger.critical("ADMIN_TOKEN not configured but admin endpoint accessed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable"
        )

    if not credentials:
        logger.warning("Admin endpoint accessed without authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(token, settings.admin_token):
        logger.warning(
            "Invalid admin token attempt",
            extra={"token_prefix": token[:4] if len(token) >= 4 else "***"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Metrics auth scheme (separate from admin)
metrics_bearer_scheme = HTTPBearer(
    scheme_name="Metrics Token",
    description="Enter your metrics token (without 'Bearer ' prefix)",
    auto_error=False,
)


@lru_cache(maxsize=1)
def _get_internal_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Parse and cache internal network CIDRs from settings.
    Uses lru_cache since networks don't change at runtime.
    """
    networks = []
    for cidr in settings.internal_networks.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as e:
            logger.warning(f"Invalid CIDR in INTERNAL_NETWORKS: {cidr} - {e}")
    return networks


def _get_client_ip(request: Request) -> str:
    """
    Get the real client IP, respecting proxy headers if configured.

    SECURITY NOTE:
    - Only trust X-Forwarded-For if you're behind a trusted proxy
    - Malicious clients can spoof this header if there's no proxy
    - Set TRUST_PROXY_HEADERS=false if exposed directly to internet
    """
    client_ip = request.client.host if request.client else "unknown"

    if settings.trust_proxy_headers:
        # X-Forwarded-For: client, proxy1, proxy2
        # The first IP is the original client
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # Some proxies use X-Real-IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip and not forwarded_for:
            client_ip = real_ip.strip()

    return client_ip


def _is_internal_ip(ip_str: str) -> bool:
    """Check if IP address is in allowed internal networks."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        logger.warning(f"Invalid IP address format: {ip_str}")
        return False

    # Check against configured networks
    for network in _get_internal_networks():
        if ip in network:
            return True

    return False


def require_internal_network(request: Request):
    """
    Dependency that only allows access from internal/private networks.

    Uses INTERNAL_NETWORKS setting (comma-separated CIDRs).
    Default: RFC1918 private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
             plus localhost (127.0.0.0/8, ::1/128)

    Example configurations:
      - Docker default bridge: 172.17.0.0/16
      - Docker custom network: 172.25.0.0/16
      - Kubernetes pod network: 10.244.0.0/16
      - Your VPN: 10.8.0.0/24

    Set INTERNAL_NETWORKS env var to customize:
      INTERNAL_NETWORKS=172.25.0.0/16,10.0.0.0/8,127.0.0.0/8
    """
    client_ip = _get_client_ip(request)

    # Debug: log raw request info
    raw_client = request.client.host if request.client else "unknown"
    xff = request.headers.get("X-Forwarded-For", "none")
    logger.debug(
        f"Internal network check: raw_client={raw_client}, xff={xff}, "
        f"resolved_ip={client_ip}, trust_proxy={settings.trust_proxy_headers}"
    )

    if _is_internal_ip(client_ip):
        logger.debug(f"Internal network access granted: {client_ip}")
        return

    logger.warning(
        f"Access denied from non-internal IP: {client_ip} (raw={raw_client})",
        extra={"client_ip": client_ip, "raw_client": raw_client, "allowed_networks": settings.internal_networks}
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden"
    )


def require_metrics_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(metrics_bearer_scheme),
):
    """
    Dependency for metrics/monitoring endpoints.

    Security model (in order of precedence):
    1. If METRICS_TOKEN is set: require Bearer token authentication
    2. If METRICS_TOKEN is not set: require internal network access

    This allows flexibility:
    - Production with external monitoring (Prometheus): use METRICS_TOKEN
    - Production with internal monitoring (same network): no token needed
    - Dev: internal network check (localhost always allowed)

    Usage:
        @app.get("/metrics", dependencies=[Depends(require_metrics_auth)])
        def metrics():
            ...

    Client examples:
        # With token:
        curl -H "Authorization: Bearer your-metrics-token" http://host/metrics

        # From internal network (no token needed):
        curl http://localhost:8099/metrics
    """
    # Strategy 1: Token-based auth (if configured)
    if settings.metrics_token:
        if not credentials:
            logger.warning("Metrics endpoint accessed without token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not hmac.compare_digest(credentials.credentials, settings.metrics_token):
            logger.warning(
                "Invalid metrics token attempt",
                extra={"token_prefix": credentials.credentials[:4] if len(credentials.credentials) >= 4 else "***"}
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return  # Token valid

    # Strategy 2: Internal network check (fallback when no token configured)
    require_internal_network(request)


class SecurityHeaders:
    """
    Middleware to add security headers.
    Implements OWASP recommended security headers.
    """

    @staticmethod
    def add_security_headers(response):
        """
        Add security headers to response.

        OWASP recommended headers for API security:
        https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
        """

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS Protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy - don't leak URLs to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (strict for API - no scripts/styles/etc)
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"

        # Permissions Policy (disable browser features)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Cache control for API responses (default no-cache, endpoints can override)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

        # HSTS (only in production with HTTPS)
        if settings.is_production or settings.is_staging:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Cross-Origin policies (additional protection)
        # Note: COOP is for popup/window interactions, safe for APIs
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # Note: CORP=cross-origin allows Twilio/external services to fetch /media
        # This is intentional - the /media endpoint needs to be fetchable by Twilio
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"

        # Hide server information
        if "Server" in response.headers:
            del response.headers["Server"]

        # Hide powered-by headers
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        return response


def mask_sensitive_data(data: dict) -> dict:
    """
    Mask sensitive fields in data before logging/returning.
    """
    sensitive_fields = {
        "password", "token", "secret", "key", "auth",
        "twilio_auth_token", "admin_token", "api_key"
    }

    masked = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in sensitive_fields):
            masked[key] = "***REDACTED***"
        elif isinstance(value, dict):
            masked[key] = mask_sensitive_data(value)
        else:
            masked[key] = value

    return masked


# Headers that should NEVER be logged (contain secrets)
SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-access-token",
}


def sanitize_headers_for_logging(headers: dict) -> dict:
    """
    Sanitize HTTP headers for safe logging.
    Redacts sensitive headers like Authorization, cookies, etc.

    SECURITY: Always use this before logging request/response headers.

    Example:
        safe_headers = sanitize_headers_for_logging(dict(request.headers))
        logger.info("Request headers", extra={"headers": safe_headers})
    """
    sanitized = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            # Show header exists but redact value
            sanitized[key] = "***REDACTED***"
        else:
            sanitized[key] = value
    return sanitized


def get_request_fingerprint(request: Request) -> str:
    """
    Generate a fingerprint for rate limiting / tracking without exposing sensitive data.
    Uses a hash of identifiable but non-sensitive attributes.

    SECURITY: This does NOT include tokens or sensitive headers.
    """
    components = [
        _get_client_ip(request),
        request.headers.get("User-Agent", ""),
        request.method,
        str(request.url.path),
    ]
    fingerprint_str = "|".join(components)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def sanitize_error_message(error: Exception, is_production: bool) -> str:
    """
    Sanitize error messages for external responses.
    In production: Generic messages
    In dev: Detailed messages
    """
    if not is_production:
        return str(error)

    # Map internal errors to generic messages
    error_type = type(error).__name__

    generic_messages = {
        "ValueError": "Invalid input",
        "KeyError": "Invalid request",
        "DatabaseError": "Service temporarily unavailable",
        "ConnectionError": "Service temporarily unavailable",
        "TimeoutError": "Request timeout",
    }

    return generic_messages.get(error_type, "An error occurred")


class RateLimitByKey:
    """
    Advanced rate limiting by custom key (IP, phone, etc.)
    Can be used for additional protection beyond global rate limiting.

    IMPORTANT: This creates a shared InMemoryRateLimiter instance that persists
    across requests to properly track rate limits.

    Example usage:
        # Limit by phone number (10 requests per minute)
        def get_phone_from_request(request: Request) -> str:
            form = await request.form()
            return form.get("From", "unknown")

        rate_limit_by_phone = RateLimitByKey(
            max_requests=10,
            window_seconds=60,
            key_func=get_phone_from_request
        )

        @app.post("/webhook", dependencies=[Depends(rate_limit_by_phone)])
        async def webhook(request: Request):
            # Endpoint protected by phone number rate limiting
            ...
    """

    def __init__(self, max_requests: int, window_seconds: int, key_func: Callable):
        from app.infra.rate_limiter import InMemoryRateLimiter

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_func = key_func
        # Create shared limiter instance (persists across requests)
        self.limiter = InMemoryRateLimiter(max_requests, window_seconds)

    async def __call__(self, request: Request):
        # Get key from request
        key = self.key_func(request)

        # Check rate limit using shared limiter
        allowed, retry_after = self.limiter.is_allowed(key)

        if not allowed:
            masked = key[:4] + "***" if len(key) > 4 else "***"
            logger.warning(
                "Rate limit exceeded for key: %s", masked,
                extra={"key_masked": masked, "retry_after": retry_after}
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(retry_after)} if retry_after else None,
            )


# =============================================================================
# Signed Media URLs (for /media endpoint)
# =============================================================================
# Photos are served via /media/{photo_id}. Telegram/WhatsApp servers fetch
# these URLs to embed images in operator notifications.
#
# In production/staging the endpoint requires a signed URL:
#   /media/{photo_id}?sig=<HMAC>&exp=<unix_timestamp>
#
# The signature uses ADMIN_TOKEN as the HMAC key (already configured, strong,
# validated at startup). Expiration prevents indefinite reuse of intercepted URLs.
# In dev mode, unsigned access is allowed for convenience.
# =============================================================================


def _get_media_signing_key() -> str | None:
    """Return the effective media signing key (EPIC G: dedicated key, fallback none)."""
    return settings.media_signing_key


def generate_media_signature(photo_id: str, expires: int) -> str:
    """
    Generate HMAC-SHA256 signature for a media URL.

    Args:
        photo_id: The photo/asset UUID string
        expires: Unix timestamp when the URL expires

    Returns:
        Truncated hex signature (16 chars) — compact but sufficient
        for time-limited URLs.
    """
    key = _get_media_signing_key()
    if not key:
        raise RuntimeError("MEDIA_SIGNING_KEY required for media URL signing")

    signing_string = f"{photo_id}:{expires}"
    sig = hmac.new(
        key.encode(),
        signing_string.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    return sig


def generate_signed_media_url(base_url: str, photo_id: str) -> str:
    """
    Build a full signed media URL: {base_url}/media/{photo_id}?sig=...&exp=...

    Uses media_url_ttl_seconds from settings for expiration.
    """
    expires = int(time.time()) + settings.media_url_ttl_seconds
    sig = generate_media_signature(str(photo_id), expires)
    return f"{base_url}/media/{photo_id}?sig={sig}&exp={expires}"


def verify_media_signature(photo_id: str, sig: str, exp: str) -> tuple[bool, str | None]:
    """
    Verify HMAC signature and expiration for a media URL.

    Args:
        photo_id: The photo/asset UUID from the URL path
        sig: The signature from ?sig= query param
        exp: The expiration timestamp from ?exp= query param

    Returns:
        (is_valid, error_message)
    """
    key = _get_media_signing_key()
    if not key:
        return False, "Server misconfigured (no signing key)"

    # Parse and check expiration
    try:
        expires = int(exp)
    except (ValueError, TypeError):
        return False, "Invalid expiration"

    if time.time() > expires:
        return False, "URL expired"

    # Recompute and compare (constant-time)
    expected_sig = generate_media_signature(photo_id, expires)

    if not hmac.compare_digest(sig, expected_sig):
        return False, "Invalid signature"

    return True, None
