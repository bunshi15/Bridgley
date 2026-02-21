# Bridgley - Production-Ready Lead Capture System

A secure, production-ready conversational bot for capturing moving/delivery service leads via WhatsApp, Telegram, and Meta Cloud API.

---

## Features

### Core Functionality
- **Multi-step conversational flow** — natural conversation for lead capture
- **Photo upload support** — collect cargo photos via WhatsApp/Telegram
- **Multi-pickup locations** — up to 3 pickup points per lead
- **Pricing estimate** — automatic item-based pricing shown before confirmation
- **GPS location input** — accept coordinates as address alternative
- **Landing prefill** — detect structured website messages, pre-fill state
- **Idempotent message processing** — handles duplicate webhook deliveries
- **Session persistence** — maintains conversation state in PostgreSQL (JSONB)
- **Lead finalization** — atomic lead save + operator notification

### Tri-Language UX (he / en / ru)
- **Automatic language detection** — script-based heuristic (Hebrew / Cyrillic / Latin)
- **Session language switching** — language persists across conversation turns
- **Static translations** — all bot prompts pre-translated in 3 languages
- **Operator lead translation** — external API translation (DeepL / Google / OpenAI) of final lead payload

### Multi-Channel Support
- **Twilio** — WhatsApp / SMS
- **Meta Cloud API** — WhatsApp Business
- **Telegram** — Bot API (webhook + long-polling)

### Security (Production-Ready)
- **Environment-based access control** — dev endpoints hidden in production
- **Admin token authentication** — constant-time comparison to prevent timing attacks
- **Webhook signature validation** — HMAC-SHA1 (Twilio), HMAC-SHA256 (Meta, Telegram)
- **Tenant credential encryption** — Fernet-based, per-tenant key isolation
- **OWASP security headers** — XSS, clickjacking, MIME sniffing protection
- **Error sanitization** — no sensitive data leaked in errors or logs
- **Rate limiting** — per-IP + per-chat sliding window
- **LOG_LEVEL=DEBUG blocked in production**

### Infrastructure
- **Runtime separation** — `RUN_MODE` splits into web / worker / poller processes
- **Database resilience** — retry logic, circuit breaker, connection pooling
- **Comprehensive metrics** — counters and histograms for monitoring
- **Health checks** — liveness and readiness probes
- **Structured logging** — JSON logging with sensitive data masking
- **Background job queue** — async processing with polling and batch settings
- **S3/MinIO photo storage** — signed URLs with TTL

---

## Quick Start

### Development

```bash
# Clone repository
git clone <your-repo>
cd bridgley

# Start development environment
docker-compose up -d

# Check health
curl http://localhost:8099/health

# View logs
docker-compose logs -f app

# Run tests
docker-compose exec app pytest tests/ -v
```

### Production

```bash
# Copy environment template
cp .env.production.example .env

# Generate strong credentials
python -c "import secrets; print('ADMIN_TOKEN=' + secrets.token_urlsafe(32))"

# Edit .env with your values (Twilio credentials, etc.)
nano .env

# Deploy
docker-compose -f docker-compose.prod.example.yml --env-file .env up -d

# Verify
curl http://localhost:8099/health
```

**Full deployment guide:** [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)

---

## Architecture

### Clean Architecture (Hexagonal)

```
app/
├── core/
│   ├── engine/             # Universal engine, bot types, domain models
│   ├── bots/               # Bot configs, translations, validators, pricing
│   ├── handlers/           # Bot handler implementations
│   ├── i18n/               # Language detection, translation providers
│   ├── ports.py            # Interfaces (SessionStore, LeadRepository)
│   └── use_cases.py        # Application services
├── infra/
│   ├── pg_session_store_async.py   # Session persistence (JSONB)
│   ├── pg_lead_repo_async.py       # Lead storage
│   ├── notification_service.py     # Operator notification formatting
│   ├── notification_channels.py    # WhatsApp/Telegram/Email channels
│   ├── crypto.py                   # Tenant credential encryption
│   ├── tenant_registry.py          # Multi-tenant config resolution
│   ├── media_fetchers/             # Photo download (Twilio/Meta/Telegram)
│   ├── metrics.py                  # Counters, histograms
│   └── logging_config.py           # Structured JSON logging
└── transport/
    ├── http_app.py          # FastAPI app (lifespan, routing, RUN_MODE)
    ├── adapters.py          # Provider adapters (Twilio, Meta, Telegram)
    ├── meta_sender.py       # Meta Cloud API sender
    ├── telegram_sender.py   # Telegram Bot API sender
    ├── security.py          # Auth, webhook validation
    └── middleware.py        # HTTP middleware
```

### Security Layers

```
┌─────────────────────────────────────────────────────────┐
│  PUBLIC (No Auth)                                        │
│  - /health               ← Load balancer health check   │
│  - /ready                ← Kubernetes readiness probe   │
│  - /webhooks/twilio      ← Signature validated          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ADMIN (Require X-Admin-Token header)                   │
│  - /health/detailed      ← System diagnostics           │
│  - /metrics              ← Operational metrics          │
│  - /admin/cleanup        ← Manual operations            │
│  - /admin/metrics/reset  ← Dangerous operations         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  DEV-ONLY (Hidden in production, return 404)            │
│  - /                     ← API info                     │
│  - /dev/chat             ← Testing endpoint             │
│  - /dev/media            ← Testing endpoint             │
│  - /docs                 ← Swagger UI (disabled)        │
└─────────────────────────────────────────────────────────┘
```

---

## Conversation Flow

1. **WELCOME** — initial greeting (or landing prefill detection)
2. **CONFIRM_ADDRESSES** — *(landing only)* ask whether to extend city-only addresses
3. **CARGO** — "What needs to be moved?" (auto-detects items + volume)
4. **VOLUME** — *(optional)* move size category if cargo is vague
5. **PICKUP_COUNT** — 1, 2, or 3 pickup locations
6. **ADDR_FROM / FLOOR_FROM** — pickup address + floor/elevator (repeats for multi-pickup)
7. **ADDR_TO / FLOOR_TO** — delivery address + floor/elevator
8. **DATE** — move date (tomorrow, this week, specific date, natural language)
9. **TIME_SLOT** — time of day (morning, afternoon, evening, exact)
10. **PHOTO_MENU / PHOTO_WAIT** — optional photo collection
11. **EXTRAS** — extra services (movers, assembly, packing)
12. **ESTIMATE** — pricing estimate shown, user confirms or restarts
13. **DONE** — lead captured, operator notified, payload translated

**Language:** auto-detected from user input (he / en / ru), persists across session.

**Intent Detection** (all three languages):
- `reset` — start over (заново, reset, התחל מחדש)
- `done_photos` — finish upload (готово, done, סיימתי)
- `no` — decline (нет, no, לא)
- `yes` — confirm (да, yes, כן)

---

## Environment Variables

### Required (Production)

```bash
APP_ENV=prod
TENANT_ID=investor_01
DATABASE_URL=postgresql://user:pass@host:5432/stage0
ADMIN_TOKEN=<32+ characters>
REQUIRE_WEBHOOK_VALIDATION=true

# At least one channel provider
CHANNEL_PROVIDER=meta   # or "twilio" or "telegram"
```

### Runtime Separation

```bash
RUN_MODE=web             # "all" | "web" | "worker" | "poller"
JOB_WORKER_ENABLED=false # enable in worker service only
```

### Operator Lead Translation (optional)

```bash
OPERATOR_LEAD_TRANSLATION_ENABLED=false
OPERATOR_LEAD_TARGET_LANG=ru           # "ru" | "en" | "he"
TRANSLATION_PROVIDER=none              # "none" | "deepl" | "google" | "openai"
TRANSLATION_API_KEY=                   # required if provider != none
TRANSLATION_TIMEOUT_SECONDS=10
TRANSLATION_RETRIES=2
TRANSLATION_RATE_LIMIT_PER_MINUTE=60
```

See [.env.production.example](.env.production.example) for complete list.

---

## API Endpoints

### Public Endpoints

```bash
# Health check (no auth)
GET /health
→ {"status": "healthy"}

# Readiness probe (no auth)
GET /ready
→ {"status": "healthy"}

# Twilio webhook (signature validated)
POST /webhooks/twilio
→ TwiML response
```

### Admin Endpoints (Require X-Admin-Token)

```bash
# Detailed health check
GET /health/detailed
-H "X-Admin-Token: your-token"
→ {"status": "healthy", "checks": {...}}

# Operational metrics
GET /metrics
-H "X-Admin-Token: your-token"
→ {"counters": {...}, "histograms": {...}}

# Manual cleanup
POST /admin/cleanup
-H "X-Admin-Token: your-token"
→ {"ok": true, "deleted_sessions": 5}
```

### Dev Endpoints (Only in APP_ENV=dev)

```bash
# API info
GET /
→ {"service": "Bridgley", "version": "1.1.0", ...}

# Test chat endpoint
POST /dev/chat
{"chat_id": "test123", "text": "Hello"}
→ {"reply": "...", "step": "cargo", "lead_id": "..."}

# API docs
GET /docs
→ Swagger UI
```

---

## Testing

### Unit Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/test_use_cases.py -v
```

**Test Coverage (979 tests):**
- `tests/test_moving_bot.py` — conversation flow, landing prefill, volume, multi-pickup
- `tests/test_translation.py` — language detection, providers, lead translation, persistence
- `tests/test_notification.py` — formatting, multi-pickup, geo, region, template fallback
- `tests/test_infrastructure.py` — run mode, job worker, startup guards
- `tests/test_crypto.py` — encryption, context mismatch, key rotation
- `tests/test_cross_tenant_isolation.py` — credential isolation
- `tests/test_domain.py` — domain models
- `tests/test_adapters.py` — provider adapters
- `tests/test_use_cases.py` — business logic
- `tests/test_moving_bot_geo.py` — geo classification, route bands
- `tests/test_localities.py` — locality lookup, RU aliases
- `tests/test_geocoding.py` — reverse geocoding
- `tests/test_security.py` — auth, middleware, headers
- `tests/test_webhooks.py` — webhook validation (Twilio, Meta, Telegram)
- **Total: 979 tests, all passing**

---

## Deployment

### Docker Files

- **Dockerfile** - Development build (with debugging tools)
- **Dockerfile.prod** - Production build (multi-stage, minimal, ~400MB)
- **Dockerfile.debug** - Debug variant with PostgreSQL client

### Docker Compose Files

- **docker-compose.yml** - Development orchestration
- **docker-compose.prod.yml** - Production orchestration

### Deployment Steps

1. **Prepare environment**
   ```bash
   cp .env.production.example .env
   ```

2. **Generate credentials**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **Configure .env file**
   - Set ADMIN_TOKEN (32+ chars)
   - Set Twilio credentials
   - Set database password

4. **Deploy**
   ```bash
   docker-compose -f docker-compose.prod.example.yml --env-file .env up -d
   ```

5. **Verify**
   ```bash
   curl http://localhost:8099/health
   ```

6. **Configure Twilio webhook**
   - URL: `https://your-domain.com/webhooks/twilio`
   - Method: POST

**Full guide:** [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)

---

## Security

### Best Practices Implemented

- ✅ Environment-based access control (dev vs prod)
- ✅ Admin token with constant-time comparison
- ✅ Webhook signature validation (HMAC-SHA1)
- ✅ OWASP security headers on all responses
- ✅ Rate limiting per IP
- ✅ Input validation with Pydantic
- ✅ SQL injection prevention (parameterized queries)
- ✅ Error sanitization in production
- ✅ Sensitive data masking in logs
- ✅ Non-root Docker user
- ✅ Read-only root filesystem support
- ✅ CORS restrictions in production

### Security Checklist

Before production:
- [ ] `APP_ENV=prod`
- [ ] `ADMIN_TOKEN` is 32+ characters
- [ ] `REQUIRE_WEBHOOK_VALIDATION=true`
- [ ] All Twilio credentials configured
- [ ] SSL/TLS certificate installed
- [ ] Firewall rules configured
- [ ] Database not exposed externally
- [ ] Monitoring/alerts set up

**Full guide:** [SECURITY_GUIDE.md](SECURITY_GUIDE.md)

---

## Monitoring

### Metrics

```bash
# Get metrics (requires admin token)
curl -H "X-Admin-Token: your-token" http://localhost:8099/metrics
```

**Key Metrics:**
- `leads_created_total` - Total leads captured
- `webhook_validation_failures_total` - Webhook signature failures
- `admin_auth_failures_total` - Failed admin auth attempts
- `database_errors_total` - Database error count
- `rate_limit_exceeded_total` - Rate limit violations
- `database_query_duration_seconds` - Query performance

### Health Checks

```bash
# Basic health (public)
curl http://localhost:8099/health

# Detailed health (admin only)
curl -H "X-Admin-Token: your-token" \
  http://localhost:8099/health/detailed
```

### Alerts

Set up alerts for:
- Webhook validation failures > 5/min
- Database errors > 10/min
- Admin auth failures > 10/hour
- Health check failures

---

## Documentation

- **[CHANGELOG.md](CHANGELOG.md)** — version history and phase milestones
- **[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)** — complete deployment guide
- **[SECURITY_GUIDE.md](SECURITY_GUIDE.md)** — security reference and hardening
- **[UNIVERSAL_ENGINE_GUIDE.md](UNIVERSAL_ENGINE_GUIDE.md)** — multi-bot architecture guide

---

## Tech Stack

- **Python 3.13** — runtime
- **FastAPI 0.128** — web framework
- **PostgreSQL 17** — database (JSONB state storage)
- **asyncpg** — async PostgreSQL driver
- **Pydantic 2.12** — data validation and settings
- **httpx** — async HTTP client (translation APIs, media fetching)
- **Twilio SDK 9.10** — WhatsApp/SMS integration
- **cryptography** — Fernet tenant credential encryption
- **Pillow** — image security re-encoding
- **boto3** — S3/MinIO photo storage
- **Docker & Docker Compose** — containerization
- **pytest + pytest-asyncio** — testing (979 tests)

---

## Project Structure

```
stage0_bot/
├── app/
│   ├── core/
│   │   ├── engine/         # Universal engine, domain models, bot types
│   │   ├── bots/           # Moving bot config, texts, validators, pricing, geo
│   │   ├── handlers/       # Bot handler implementations
│   │   └── i18n/           # Translation providers, lead translator
│   ├── infra/              # DB, notifications, crypto, media, metrics
│   └── transport/          # FastAPI, adapters, senders, security
├── tests/                  # 979 tests
├── scripts/                # deploy.sh, backup_db.sh, generate_encryption_key.py
├── docker-compose.prod.example.yml   # Production (web/worker/poller separation)
├── docker-compose.staging.yml        # Staging with full infra
├── docker-compose.example.yml        # Development
├── .env.production.example           # Environment template
└── obsolete/               # Archived specs and docs
```

---

## Contributing

### Code Style

```bash
# Format code
black app/ tests/

# Lint
ruff check app/ tests/

# Type check
mypy app/
```

### Testing

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

### Commit Messages

Use conventional commits:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `test:` - Tests
- `refactor:` - Refactoring
- `chore:` - Maintenance

---

## License

Proprietary - All rights reserved

---

## Support

For issues:
1. Check logs: `docker-compose logs -f app`
2. Review documentation in this README
3. Check [SECURITY_GUIDE.md](SECURITY_GUIDE.md)
4. Check [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

**See [CHANGELOG.md](CHANGELOG.md) for full history.**

---

**Built with security and reliability in mind. Ready for production! 🚀🔒**
