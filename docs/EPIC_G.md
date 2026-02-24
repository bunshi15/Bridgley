# EPIC G — Secure Media Intake + Optimized Operator Delivery

---

## Context

Current media pipeline is **image-only**:

* `MediaService.process_media_item()` skips non-images.
* `handle_process_media` processes only photos.
* `S3Storage` is photo-oriented (`photos/{tenant}/{id}.{ext}`).
* Operator notifications support `photo_urls`, not generic media links.

Pricing engine (`moving_bot_v1/pricing.py`) supports routing bands and underpricing guards but lacks structured **complexity classification**, leading to underestimation of large / complex moves.

---

## Goals

1. Accept inbound **video attachments** safely.
2. Store media privately in S3/MinIO.
3. Deliver media to operators via **secure short-lived links**.
4. Optimize cost when many photos are sent.
5. Introduce pricing complexity guards to prevent severe underestimation.
6. Keep architecture modular for future transcription service.

---

## Non-goals (v1)

* No local LLM.
* No heavy video processing.
* No object detection.
* No additional mandatory user questions.

---

# G1 — Media Domain Extension

## G1.1 Create Generic `media_assets` Table

Migration: `011_add_media_assets_table.sql`

Fields:

* `id uuid primary key`
* `tenant_id text not null`
* `lead_id text null`
* `chat_id text not null`
* `provider text not null`
* `message_id text null`
* `kind text not null` (`image|video|audio|document`)
* `content_type text not null`
* `size_bytes int not null`
* `filename text not null` (UUID-based)
* `s3_key text not null`
* `expires_at timestamptz null`
* `created_at timestamptz default now()`

Indexes:

* `(tenant_id, lead_id)`
* `(tenant_id, chat_id)`
* `(expires_at)`

Security principles:

* No public URLs stored.
* Only private S3 keys persisted.

---

## G1.2 Repository Layer

Create:

```
pg_media_asset_repo_async.py
```

Capabilities:

* Save media asset
* List media by lead
* Fetch by asset_id
* Delete expired assets

---

# G2 — Storage Layer (Private Media Only)

## G2.1 Extend S3 Storage to Generic Object Storage

Required methods:

* `put_object(key, bytes, content_type)`
* `delete_object(key)`
* `generate_presigned_get_url(key, expires_seconds)`

Key format:

```
media/{tenant_id}/{lead_id}/{asset_id}.{ext}
```

Security requirements:

* UUID-based filenames only
* Content-type allowlist
* Size limits:

  * images: existing limit
  * videos: configurable (e.g. 64MB)
* Bucket must remain private
* Presigned URL expiration ≤ 30 minutes

---

## G2.2 TTL Cleanup

Periodic job:

* Find expired `media_assets`
* Delete S3 object
* Delete DB row

Must be idempotent.

---

# G3 — Inbound Media Handling

## G3.1 Extend `handle_process_media`

Logic:

If `image/*`:

* Keep current behavior

If `video/*`:

1. Download
2. Validate size + content-type
3. Upload raw bytes to S3
4. Save row in `media_assets`
5. Set `expires_at = now() + MEDIA_TTL_DAYS`

No re-encoding in v1.

---

## G3.2 Ensure Lead Association

Webhook must enqueue job with:

* `tenant_id`
* `chat_id`
* `message_id`
* `lead_id`
* `media_items`

Avoid resolving lead by session to prevent race conditions.

---

# G4 — Unified Secure Media Delivery

## G4.1 Generic Media Endpoint

Replace photo-only endpoint with:

```
GET /media/{asset_id}?sig=...&exp=...
```

Flow:

1. Validate expiration
2. Validate HMAC using `MEDIA_SIGNING_KEY`
3. Load media asset
4. Generate S3 presigned URL (5–30 min)
5. Return HTTP 302 redirect

Signature:

```
HMAC(MEDIA_SIGNING_KEY, f"{tenant}:{kind}:{asset_id}:{exp}")
```

Security upgrades:

* Separate `MEDIA_SIGNING_KEY`
* Minimum 32 hex characters
* Do not log full URLs

Why redirect:

* Avoid streaming large video through FastAPI
* Avoid memory pressure
* Let S3 handle Range requests

---

# G4.2 Photo Threshold Optimization

Introduce config:

```
MAX_INLINE_MEDIA_COUNT = 5
```

Rules:

| Media Type | Count       | Delivery          |
| ---------- | ----------- | ----------------- |
| Image      | ≤ threshold | Inline attachment |
| Image      | > threshold | Signed links only |
| Video      | Any         | Signed link only  |

Benefits:

* Reduce outbound API cost
* Avoid provider media limits
* Keep operator message size controlled

---

# G4.3 Logging Rules

Log only:

* asset_id (first 8 chars)
* tenant
* media type

Never log:

* full presigned URLs
* raw S3 URLs

---

# G5 — Future Transcription Hook (Optional)

Add nullable fields:

* `transcript_text`
* `transcript_status`
* `transcript_provider`

Future service:

1. Download video
2. Extract audio
3. Send to STT API
4. Store transcript

Not part of v1 runtime.

---

# G7 — Acceptance Criteria

## Functional

* Video attachments stored in S3.
* Operator receives secure link.
* Photos limited inline by threshold.
* Media auto-deletes after TTL.

## Security

* No public bucket exposure.
* Presigned links short-lived.
* HMAC validation enforced.
* Content-type allowlist.
* UUID-based object keys.

## Performance

* Webhooks remain asynchronous.
* No large streaming through app.
* Cleanup job idempotent.

---

# Implementation Order

1. DB: create `media_assets`
2. S3: generic object support
3. Worker: extend media handler
4. API: unified `/media/{asset_id}`
5. Notify: threshold logic
6. Cleanup job

---

# Result

* Secure media ingestion.
* Cost-optimized operator delivery.
* No heavy video processing.
* Architecture ready for STT v2.

---

# Implementation Status

| Section | Status | Notes |
|---------|--------|-------|
| G1.1 media_assets table | DONE | `011_add_media_assets_table.sql` |
| G1.2 Repository layer | DONE | `pg_media_asset_repo_async.py` |
| G2.1 Generic S3 storage | DONE | `put_object`, `delete_object`, `generate_presigned_get_url` |
| G2.2 TTL cleanup | DONE | `handle_media_cleanup` + `/admin/media/cleanup` |
| G3.1 Video in handle_process_media | DONE | Routes `video/*` to `process_video_item` |
| G3.2 Lead association | DONE | `lead_id` passed in job payload, `link_to_lead` |
| G4.1 Generic /media endpoint | DONE | Falls back to `media_assets` after `photos` |
| G4.2 Photo threshold | DONE | `_get_media_for_lead` with `max_inline_media_count` |
| G4.3 Logging rules | DONE | Only `asset_id[:8]` logged |
| G5 Transcription hook | DONE | Nullable fields in migration |
| G6 Pricing complexity guards | DONE | (Previous sessions) |
| G7 Acceptance criteria | DONE | 40 tests in `test_media_assets.py` |

EPIC G is fully implemented. Here's a summary:

## EPIC G — Secure Media Intake + Optimized Operator Delivery: COMPLETE

**Files created (3):**
- `app/infra/sql/011_add_media_assets_table.sql` — DB migration with G5 transcription fields
- `app/infra/pg_media_asset_repo_async.py` — Repository (save, get_by_id, get_for_lead, link_to_lead, delete_expired)
- `tests/test_media_assets.py` — 40 new tests

**Files modified (7):**
- `app/config.py` — 5 new settings + schema version bump
- `app/infra/s3_storage.py` — 4 new methods (build_media_key, put_object, delete_object, generate_presigned_get_url)
- `app/infra/media_service.py` — `process_video_item()` method + video ext mapping
- `app/infra/job_worker.py` — Video routing in `handle_process_media` + `handle_media_cleanup`
- `app/transport/http_app.py` — `/media/{id}` fallback to media_assets + `/admin/media/cleanup` + handler registration
- `app/transport/security.py` — `_get_media_signing_key()` with `media_signing_key` fallback
- `app/infra/notification_service.py` — `_get_media_for_lead()` with G4.2 threshold + `_MediaDelivery` dataclass

**Test results:** 1307 passed, 0 failures (was 1267, +40 new)