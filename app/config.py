# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_env: Literal["dev", "staging", "prod"] = "dev"
    run_mode: Literal["all", "web", "worker", "poller"] = "all"
    tenant_id: str = "investor_01"
    log_level: str = "INFO"

    # Database
    expected_schema_version: str = "011_add_media_assets_table.sql"  # Update on deploy when new migrations are added
    database_url: str | None = None
    pghost: str = "localhost"
    pgport: int = 5432
    pguser: str = "postgres"
    pgpassword: str = ""
    pgdatabase: str = "postgres"
    pg_pool_min: int = 2
    pg_pool_max: int = 20
    pg_connect_timeout: int = 5
    pg_statement_timeout_ms: int = 30000
    pg_idle_in_tx_timeout_ms: int = 30000

    # Session Management
    session_ttl_seconds: int = 21600  # 6 hours
    session_stale_hint_seconds: int = 3600  # 1 hour — show "you can reset" hint after this inactivity

    # Security
    admin_token: str | None = None
    twilio_auth_token: str | None = None
    allowed_origins: list[str] = ["*"]
    rate_limit_per_minute: int = 60
    chat_rate_limit_per_minute: int = 10  # Max messages per chat per minute (anti-spam)
    admin_host: str | None = None  # e.g., "bot-admin.example.com" - admin endpoints only accessible on this host

    # Admin Authentication Mode
    # "bearer" - Simple Bearer token (Authorization: Bearer <token>)
    # "hmac" - HMAC request signing (X-Timestamp + X-Signature headers)
    # "both" - Accept either method (useful during migration)
    admin_auth_mode: Literal["bearer", "hmac", "both"] = "both"

    # Channel Provider Selection
    # "twilio" - Use Twilio for WhatsApp messaging (default)
    # "meta" - Use Meta WhatsApp Cloud API directly
    # "telegram" - Use Telegram Bot API
    channel_provider: Literal["twilio", "meta", "telegram"] = "twilio"

    # Twilio
    twilio_account_sid: str | None = None
    twilio_phone_number: str | None = None
    twilio_webhook_url: str | None = None  # Public URL for signature validation (e.g., https://bot.example.com/webhooks/twilio)
    operator_whatsapp: str | None = None  # Operator WhatsApp number to receive lead notifications (e.g., +1234567890)
    twilio_content_sid: str | None = None  # Twilio Content Template SID for 24h window fallback (e.g., HX...)

    # Meta WhatsApp Cloud API
    meta_access_token: str | None = None  # Long-lived access token for Graph API
    meta_phone_number_id: str | None = None  # Phone Number ID from Meta Business Suite
    meta_waba_id: str | None = None  # WhatsApp Business Account ID (optional)
    meta_webhook_verify_token: str | None = None  # Token for webhook verification handshake
    meta_graph_api_version: str = "v20.0"  # Graph API version
    meta_app_secret: str | None = None  # App secret for signature verification (optional)

    # Outbound Message Queue (handles Twilio rate limits)
    outbound_messages_per_second: float = 1.0  # Twilio sandbox: 1/sec, production: higher
    outbound_max_retries: int = 3
    outbound_base_retry_delay: float = 5.0  # seconds, doubles on each retry

    # Operator Notifications
    operator_notifications_enabled: bool = True  # Master switch to disable all notifications
    operator_notification_channel: Literal["whatsapp", "telegram", "email"] = "whatsapp"
    # Provider for WhatsApp operator notifications:
    # "twilio" — send via Twilio (existing, default)
    # "meta"   — send via Meta WhatsApp Cloud API
    operator_whatsapp_provider: Literal["twilio", "meta"] = "twilio"

    # Telegram notifications (if notification channel = "telegram")
    telegram_bot_token: str | None = None  # Bot token from @BotFather (for notifications)
    telegram_chat_id: str | None = None  # Chat/group ID to send notifications to

    # Telegram Channel (when channel_provider = "telegram")
    # Separate token to allow a different bot for conversations vs notifications.
    # If not set, falls back to telegram_bot_token.
    telegram_channel_bot_token: str | None = None
    telegram_channel_mode: Literal["polling", "webhook"] = "polling"
    telegram_webhook_secret: str | None = None  # Secret token for webhook validation (X-Telegram-Bot-Api-Secret-Token)

    # Email notifications (if channel = "email") - placeholder for future
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    operator_email: str | None = None

    # S3/Bucket Storage (for photos)
    s3_endpoint_url: str | None = None  # e.g., https://s3.amazonaws.com or https://xyz.r2.cloudflarestorage.com
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket_name: str | None = None
    s3_region: str = "auto"
    s3_public_url: str | None = None  # Public URL prefix for serving files (e.g., https://cdn.example.com)
    s3_force_path_style: bool = True

    # Monitoring & Metrics
    sentry_dsn: str | None = None
    enable_metrics: bool = True
    metrics_token: str | None = None  # Optional token for /metrics, /health/detailed (if not set, uses internal network check)

    # Internal Network Access (for metrics/health endpoints when no token)
    # Comma-separated CIDR ranges, e.g. "172.16.0.0/12,10.0.0.0/8"
    # Default: RFC1918 private ranges + localhost
    internal_networks: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128"
    # SECURITY: Only set to true if behind a trusted reverse proxy (nginx, cloudflared, etc.)
    # When false, uses direct client IP - safer default, prevents X-Forwarded-For spoofing
    trust_proxy_headers: bool = False

    # Media URL Security
    # TTL for signed /media URLs (used in operator notifications).
    # Telegram/WhatsApp servers fetch photos via these URLs.
    media_url_ttl_seconds: int = 3600  # 1 hour

    # EPIC G: Video/Media settings
    media_video_max_size_mb: int = 64                # Max video upload size
    media_ttl_days: int = 90                          # Auto-expire media assets after N days
    media_signing_key: str | None = None              # Separate HMAC key for media URLs; falls back to admin_token
    max_inline_media_count: int = 5                   # G4.2 photo threshold: above this → signed links only
    media_allowed_video_types: str = "video/mp4,video/quicktime,video/webm,video/3gpp"

    # Job Worker (v0.7 DB-backed queue)
    job_worker_enabled: bool = False          # Master switch — enable explicitly in worker service
    job_worker_poll_interval: float = 1.0     # Seconds between polls when idle
    job_worker_batch_size: int = 5            # Jobs claimed per poll cycle
    job_worker_base_retry_delay: float = 5.0  # Base delay for exponential backoff (seconds)
    job_worker_stale_timeout: int = 300       # Reset jobs stuck 'running' for this long (seconds)
    job_cleanup_completed_ttl_days: int = 7   # Delete completed jobs older than N days
    job_cleanup_failed_ttl_days: int = 30     # Delete failed jobs older than N days

    # Multi-Tenant (v0.8)
    tenant_encryption_key: str | None = None  # Fernet key for encrypting channel credentials in DB

    # Operator Lead Translation (external API)
    operator_lead_translation_enabled: bool = False
    operator_lead_target_lang: Literal["ru", "en", "he"] = "ru"
    translation_provider: Literal["none", "deepl", "google", "openai"] = "none"
    translation_api_key: str | None = None
    translation_timeout_seconds: int = 10
    translation_retries: int = 2
    translation_rate_limit_per_minute: int = 60

    # Engine Modularization (EPIC A)
    enabled_bots: str = "moving_bot_v1"           # Comma-separated bot types to register
    worker_role: Literal["core", "dispatch", "all"] = "all"  # Job handler scope

    # Dispatch Layer — Iteration 1: Operator Fallback (Manual Copy)
    dispatch_crew_fallback_enabled: bool = False  # Send crew-safe copy-paste message alongside full lead

    # Estimate Display Control
    estimate_display_enabled: bool = True  # False = hide price from user & crew; operator still sees it
    operator_estimate_debug: bool = False  # Show estimate breakdown in operator message

    # Feature Flags
    require_webhook_validation: bool = True
    enable_request_logging: bool = True

    # Image Processing Security
    # SECURITY: WebP has had critical RCE vulnerabilities (CVE-2023-4863)
    # Set to false to only allow JPEG/PNG (safer but less compatible)
    allow_webp_images: bool = True
    allow_heic_images: bool = True  # iPhone HEIC format
    image_max_file_size_mb: int = 10  # Max upload size in MB
    image_max_pixels_millions: int = 16  # Max megapixels (16M = 4000x4000)

    # Media Download: Trusted Redirect Domains
    # Comma-separated domain suffixes where Authorization header is preserved on redirect.
    # When a media download redirects cross-origin, auth is stripped UNLESS the target
    # domain matches one of these suffixes. This prevents credential leaks to untrusted
    # CDNs while allowing auth propagation within provider ecosystems (Twilio, Meta).
    trusted_redirect_domain_suffixes: str = "twilio.com,twiliocdn.com,facebook.com,fbsbx.com,fbcdn.net,whatsapp.net"
    keep_auth_on_trusted_redirects: bool = True

    # Media Download Strategy (per provider)
    # "http"        - Generic HTTP download via MediaUrl (current behavior, default)
    # "provider_api" - Provider REST/Graph API (eliminates CDN redirect issues)
    # The generic HTTP fetcher is always available as automatic fallback.
    twilio_media_fetch_strategy: Literal["http", "provider_api"] = "http"
    meta_media_fetch_strategy: Literal["http", "provider_api"] = "http"

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"

    @property
    def is_staging(self) -> bool:
        return self.app_env == "staging"

    @property
    def s3_enabled(self) -> bool:
        """Check if S3 storage is configured"""
        return bool(
            self.s3_endpoint_url
            and self.s3_access_key
            and self.s3_secret_key
            and self.s3_bucket_name
        )

    @property
    def database_dsn(self) -> str:
        if self.database_url:
            return self.database_url

        return (
            f"host={self.pghost} port={self.pgport} "
            f"dbname={self.pgdatabase} user={self.pguser} "
            f"password={self.pgpassword} "
            f"connect_timeout={self.pg_connect_timeout} "
            f"options='-c statement_timeout={self.pg_statement_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={self.pg_idle_in_tx_timeout_ms}'"
        )

    @property
    def meta_enabled(self) -> bool:
        """Check if Meta Cloud API is configured"""
        return bool(
            self.meta_access_token
            and self.meta_phone_number_id
            and self.meta_webhook_verify_token
        )

    @property
    def telegram_channel_token(self) -> str | None:
        """Effective bot token for Telegram channel (falls back to notification token)"""
        return self.telegram_channel_bot_token or self.telegram_bot_token

    @property
    def telegram_channel_enabled(self) -> bool:
        """Check if Telegram channel is configured"""
        return bool(self.telegram_channel_token)

    def validate_required_for_production(self) -> list[str]:
        """Validate that required settings exist for production"""
        if not self.is_production:
            return []

        missing = []

        # Always required
        required_fields = [
            ("admin_token", self.admin_token),
        ]

        # Provider-specific requirements
        if self.channel_provider == "twilio":
            required_fields.extend([
                ("twilio_auth_token", self.twilio_auth_token),
                ("twilio_account_sid", self.twilio_account_sid),
                ("twilio_phone_number", self.twilio_phone_number),
            ])
        elif self.channel_provider == "meta":
            required_fields.extend([
                ("meta_access_token", self.meta_access_token),
                ("meta_phone_number_id", self.meta_phone_number_id),
                ("meta_webhook_verify_token", self.meta_webhook_verify_token),
            ])
        elif self.channel_provider == "telegram":
            required_fields.append(
                ("telegram_channel_bot_token or telegram_bot_token", self.telegram_channel_token),
            )

        for field_name, value in required_fields:
            if not value:
                missing.append(field_name)

        return missing

def warn_on_risky_config(s: "Settings") -> list[str]:
    warnings: list[str] = []

    # --- Admin / Security ---
    if s.is_production and not s.admin_token:
        warnings.append("prod: admin_token is missing (admin auth will be broken).")

    if s.admin_auth_mode in ("hmac", "both") and not s.admin_token:
        warnings.append("admin_auth_mode requires a shared secret, but admin_token is empty.")

    if s.is_production and s.allowed_origins == ["*"]:
        warnings.append("prod: allowed_origins=['*'] (CORS is wide open).")

    if not s.admin_host:
        warnings.append("admin_host is not set (admin endpoints may be accessible on the main host).")

    # --- Proxy headers trust ---
    if s.trust_proxy_headers:
        warnings.append(
            "trust_proxy_headers=True: ensure you are behind a trusted reverse proxy, "
            "otherwise X-Forwarded-For spoofing is possible."
        )

    # --- Metrics exposure ---
    if s.enable_metrics and not s.metrics_token:
        warnings.append(
            "enable_metrics=True but metrics_token is not set: metrics/health protection relies on internal_networks."
        )
    if not s.internal_networks.strip():
        warnings.append("internal_networks is empty: internal-only protection for metrics/health won't work.")

    # --- Provider configuration ---
    if s.channel_provider == "twilio":
        if not s.twilio_auth_token:
            warnings.append("channel_provider=twilio but twilio_auth_token is missing.")
        if not s.twilio_account_sid:
            warnings.append("channel_provider=twilio but twilio_account_sid is missing.")
        if not s.twilio_phone_number:
            warnings.append("channel_provider=twilio but twilio_phone_number is missing.")
        if not s.operator_whatsapp:
            warnings.append("twilio: operator_whatsapp is not set (operator notifications may fail).")
        if not s.twilio_webhook_url and s.require_webhook_validation:
            warnings.append("twilio: require_webhook_validation=True but twilio_webhook_url is not set.")
    elif s.channel_provider == "meta":
        if not s.meta_access_token:
            warnings.append("channel_provider=meta but meta_access_token is missing.")
        if not s.meta_phone_number_id:
            warnings.append("channel_provider=meta but meta_phone_number_id is missing.")
        if not s.meta_webhook_verify_token:
            warnings.append("channel_provider=meta but meta_webhook_verify_token is missing.")
        if s.require_webhook_validation and not s.meta_app_secret:
            warnings.append("meta: require_webhook_validation=True but meta_app_secret is not set (signature checks may be impossible).")
    elif s.channel_provider == "telegram":
        if not s.telegram_channel_token:
            warnings.append("channel_provider=telegram but telegram_bot_token/telegram_channel_bot_token is missing.")

    # --- S3/R2 storage ---
    if not s.s3_enabled:
        warnings.append("S3 storage is not configured (photos/uploads will not be persisted).")
    else:
        if not s.s3_public_url:
            warnings.append("s3_enabled=True but s3_public_url is not set (public links to media may be broken).")

    # --- Media security flags ---
    if s.allow_webp_images:
        warnings.append("allow_webp_images=True (ensure your image stack is patched; WebP had critical CVEs).")

    return warnings


def validate_or_warn(s: "Settings") -> None:
    """
    In prod: enforce required settings (hard fail).
    In non-prod: warn only.
    """
    missing = s.validate_required_for_production()

    # Hard errors in production
    if missing:
        # raise RuntimeError instead of warnings for prod
        raise RuntimeError(f"Missing required settings for production: {', '.join(missing)}")

    # Warnings (all envs)
    # Use your logger here if you have one available at import time.
    for msg in warn_on_risky_config(s):
        print(f"[WARN][config] {msg}")

settings = Settings()
validate_or_warn(settings)