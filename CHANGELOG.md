# Changelog

All notable changes to this project are documented in this file.

Format: phases map to feature milestones, not SemVer.

---

## [Unreleased]

_Working towards v1.0.0 — production stabilization._

### Changed
- **(EPIC A1.1) Bot package layout** — moved flat `moving_bot_*.py` modules
  into `app/core/bots/moving_bot_v1/` package with `data/` subfolder for
  JSON files. Old flat files are now 1-line re-export shims for backward
  compatibility. Added `example/` bot template for future bot creation.

---

## v0.9.8 — Dispatch Layer Iteration 1: Operator Fallback (Manual Copy)

### Added
- **Crew-safe copy-paste message** — operator receives a sanitized message
  alongside the full lead that can be forwarded to the crew WhatsApp group
  - `format_crew_message()` — CrewLeadView builder with strict PII allowlist
  - Only includes: sequential lead number, from/to locality, date, volume,
    floors, elevator info, recognised items, pricing estimate
  - **No PII**: no phone, no street address, no free text, no photos, no links
  - Crew message labels match operator's language (`operator_lead_target_lang`)
- **Sequential lead number** (`lead_seq` BIGSERIAL column)
  - DB migration `010_add_lead_seq.sql`
  - Globally auto-incrementing across tenants
  - Stored in `custom["lead_number"]` at finalization for crew/operator messages
  - Operator notification header: `📦 Заявка #N`
- **`notify_crew_fallback` job type** — enqueued on `LeadFinalized` when enabled
  - 2-second delay so full lead always arrives first
  - Idempotency key: `lead_id + "crew_fallback_v1"`
- **`dispatch_crew_fallback_enabled`** config setting (default: `false`)
  - Per-tenant override via `config_json.dispatch_crew_fallback_enabled`
- `get_dispatch_config()` helper in tenant registry
- Tri-language crew message labels (RU/EN/HE)

### Fixed
- **Address translation not loading** — translations with `"unchanged"` status
  were not applied in operator notification; now both `"ok"` and `"unchanged"`
  statuses load the translations dict and show the original reference block
- **Crew message used hardcoded English labels** — labels now follow
  `operator_lead_target_lang` setting (RU/EN/HE)
- **Crew message used UUID fragment as job ID** — replaced with sequential
  `lead_number` from DB (`#42` instead of `#0952ef82`)
- **Crew message had useless header** — removed `📣 FOR CREW (Copy to group)`
- **(EPIC D1) Item quantity inflated by attribute numbers** — `extract_items()`
  treated any digit in the fragment as quantity (e.g. "5-дверный шкаф" → qty=5,
  "холодильник 200кг" → qty=200). Now uses explicit quantity markers only
  (`x5`, `5шт`, `qty:5`, etc.) with attribute suppression (`двер`, `кг`, `см`)
  and a sanity cap (bare number > 20 → qty=1)
- **(EPIC D3) Crew message missing multi-pickup route** — crew view only showed
  first pickup floor; now renders all pickup points with per-point floors and
  elevator info, plus localized labels (Забор/Pickup/איסוף)
- **(EPIC B1.5) Dispatch code not isolated** — `format_crew_message()` and
  `notify_operator_crew_fallback()` still lived inline in `notification_service.py`;
  moved canonical implementations to `app/core/dispatch/` package with
  backward-compatible re-exports

---

## v0.9.7 — Tri-language UX & Operator Lead Translation

### Added
- **Tri-language UX & operator lead translation** (translation_release.md)
  - Script-based language detection (`detect_language()`) for Hebrew, Russian, English
  - Automatic session language switching on free-text inputs
  - `TranslationProvider` abstraction with DeepL, Google, OpenAI implementations
  - Operator lead translation pipeline (translates on finalization only)
  - `translations` + `translation_meta` payload blocks (backwards compatible)
  - Notification formatting: translated values in main body, originals in reference block
  - Session language indicator in operator notification
  - 7 new config variables (`OPERATOR_LEAD_TRANSLATION_ENABLED`, etc.)

### Fixed
- **Session language persistence** — `language`, `bot_type`, and `metadata` fields
  were not saved to / loaded from PostgreSQL. After detection, the next DB
  round-trip would reset language to `"ru"`. Now all three fields survive the
  `upsert() -> get()` cycle; old sessions without a `language` key gracefully
  default to `"ru"`.
- **DeepL API auth** — switched from `auth_key` form field to
  `Authorization: DeepL-Auth-Key` header (production fix)
- **Non-retryable HTTP errors** — 401/403 now break retry loop immediately
  instead of wasting 7+ seconds on futile retries
- **PII masking in rate limiter logs** — phone numbers / IPs now show max 4
  characters (`key[:4]***`) instead of full values
- **Operator notification language** — translated values now appear in the main
  body of the notification; originals shown in a reference "Оригинал" block

---

## Phase 15 — Production Hardening & Runtime Separation

### Added
- **RUN_MODE** setting (`all | web | worker | poller`) to split monolith into
  separate Docker services (web, worker, poller)
- `docker-compose.prod.example.yml` with YAML anchors and per-role services
- `scripts/deploy.sh` — immutable-tag deploy with rollback support
- `scripts/backup_db.sh` — timestamped `pg_dump` with rotation
- `scripts/generate_encryption_key.py` — safe Fernet key generation
- **LOG_LEVEL=DEBUG guard** — blocked in production (`is_production` check)
- Backup service under `tools` profile in Docker Compose

### Security
- Removed key-printing command from `CryptoContextMismatchError`
- Simplified error message (no tenant/provider IDs revealed)
- Stripped response body/payload/headers from all log messages
- Replaced `{exc}` with `{type(exc).__name__}` in all sender/channel logs
- Masked `download_url` in meta_fetcher DEBUG log
- Removed `file_path` from telegram_fetcher DEBUG log
- Removed `error_msg` from Meta sender auth/rate-limit logs

---

## Phase 14 — Nationwide Zone-Based Routing

### Added
- **Zone-based route classification** — inter-city band detection
  (`same_city`, `metro`, `inter_region_short`, `inter_region_long`, `cross_country`)
- Locality lookup with 1955 Russian aliases (`localities_ru_aliases.auto.json`)
- Route pricing factors based on distance bands
- Region classification in operator notification

### Changed
- Pricing engine uses route band + distance factor

---

## Phase 13 — Landing Prefill & Confirm Addresses

### Added
- `parse_landing_prefill()` — detects structured website landing messages
- `confirm_addresses` step — asks user whether to extend city-only addresses
- Date skip logic — when landing provides a parseable date, skip date step
- `_apply_prefill()` routes to correct step based on prefilled data

---

## Phase 12 — Volume Optional

### Changed
- Volume step is now **optional** — skipped when cargo has recognized items
  (`extract_items()` returns non-empty list)
- Only asks volume explicitly when no rooms AND no items detected

---

## Phase 11 — Item Extraction & Pricing

### Added
- `extract_items()` — parses cargo text into structured item list with
  multilingual aliases
- `ITEM_ALIAS_LOOKUP` with Russian/English/Hebrew item names
- Items feed into pricing estimate

---

## Phase 10 — Natural Date Parsing

### Added
- `_parse_natural_date()` — recognizes weekday names, relative days
  ("tomorrow", "in 3 days"), and month names in ru/en/he
- `parse_date()` returns structured date with validation (too_soon/too_far)

---

## Phase 9 — Volume Category

### Added
- Volume step (`small | medium | large | xl`) for move size estimation
- `detect_volume_from_rooms()` — auto-detect from room descriptions
- DB migration `009_add_volume_step.sql`

---

## Phase 8 — Region Classification

### Added
- Metro area detection (Haifa metropolitan agglomeration)
- Distance factor for out-of-metro routes
- Region classification in operator notification (warning badge)

---

## Phase 7 — Geo Location Support

### Added
- Reverse geocoding via Nominatim (optional)
- `classify_geo_points()` for distance calculation
- Google Maps links in operator notification

---

## Phase 5 — GPS Location Input

### Added
- `handle_location()` — accepts GPS coordinates as address alternative
- `LocationData` domain model
- Geo points stored in `custom["geo_points"]`
- All providers (Twilio, Meta, Telegram) support location messages

---

## Phase 4 — Multi-Pickup & Operational Hardening

### Added
- Multi-pickup flow (1-3 pickup locations with separate floors)
- `pickup_count` step, `addr_from_2/3`, `floor_from_2/3`
- Meta WhatsApp Cloud API retry logic with error classification
- Twilio 63016 content template fallback (outside 24h window)
- DB migration `008_add_multi_pickup_steps.sql`

---

## Phase 3 — Pricing Estimate

### Added
- `estimate_price()` — item-based pricing with base + per-item rates
- Estimate step shows price range before confirmation
- Estimate in operator notification (min–max range with currency)
- DB migration `007_add_scheduling_and_estimate_steps.sql`

---

## Phase 2 — Structured Scheduling

### Added
- `date` / `specific_date` / `time_slot` / `exact_time` steps
  replacing legacy single `time` step
- Date choices (tomorrow, 2-3 days, this week, specific)
- Time slots (morning, afternoon, evening, exact, flexible)
- Move date + time slot in operator notification

---

## Phase 1 — Multi-Channel & Multi-Tenant Foundation

### Added
- Universal engine architecture (`BotConfig`, `BotRegistry`, `BotHandler` protocol)
- Meta WhatsApp Cloud API adapter
- Telegram Bot API adapter (webhook + long-polling)
- Multi-tenant support (`tenant_id`, `TenantContext`, per-tenant config)
- Tenant credential encryption (Fernet-based `CryptoContextMismatchError`)
- Job queue for async processing (`jobs` table)
- S3/MinIO photo storage with signed URLs
- Operator notifications via WhatsApp (Twilio/Meta) and Telegram
- Session persistence in PostgreSQL with JSONB state
- Idempotent webhook processing
- Security: OWASP headers, rate limiting, webhook signature validation
- Admin API with token auth and HMAC support
- Health checks (liveness + readiness)
- Structured JSON logging with sensitive data masking

### Database
- `001_init.sql` — sessions, leads tables
- `002_add_leads_updated_at.sql` — updated_at column
- `003_add_photos_table.sql` — photos storage
- `004_add_addr_floor_steps.sql` — address/floor step support
- `005_add_jobs_table.sql` — background job queue
- `006_add_tenants_and_channel_bindings.sql` — multi-tenant schema
