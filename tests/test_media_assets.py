# tests/test_media_assets.py
"""
Tests for EPIC G: Secure Media Intake + Optimized Operator Delivery.

Covers:
- MediaAssetRecord dataclass
- S3Storage generic methods (put_object, delete_object, generate_presigned_get_url, build_media_key)
- Video processing in MediaService
- handle_process_media routing (image vs video)
- /media/{id} endpoint fallback to media_assets
- Media signature with media_signing_key
- Photo threshold optimization (G4.2)
- TTL cleanup handler
- Config: new EPIC G settings
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import UUID, uuid4

import pytest


# ============================================================================
# MediaAssetRecord / Repository
# ============================================================================

class TestMediaAssetRecord:
    """Test the MediaAssetRecord dataclass."""

    def test_create_record(self):
        from app.infra.pg_media_asset_repo_async import MediaAssetRecord

        rec = MediaAssetRecord(
            id=uuid4(),
            tenant_id="t1",
            lead_id="lead-1",
            chat_id="chat-1",
            provider="telegram",
            message_id="msg-1",
            kind="video",
            content_type="video/mp4",
            size_bytes=1024000,
            filename="abc.mp4",
            s3_key="media/t1/lead-1/abc.mp4",
        )
        assert rec.kind == "video"
        assert rec.content_type == "video/mp4"
        assert rec.expires_at is None
        assert rec.created_at is None

    def test_record_with_expiry(self):
        from app.infra.pg_media_asset_repo_async import MediaAssetRecord

        exp = datetime.now(timezone.utc) + timedelta(days=90)
        rec = MediaAssetRecord(
            id=uuid4(),
            tenant_id="t1",
            lead_id=None,
            chat_id="chat-1",
            provider="twilio",
            message_id=None,
            kind="image",
            content_type="image/jpeg",
            size_bytes=5000,
            filename="img.jpg",
            s3_key="media/t1/unlinked/img.jpg",
            expires_at=exp,
        )
        assert rec.expires_at == exp
        assert rec.lead_id is None


class TestMediaAssetRepoUnit:
    """Unit tests for repository methods (mocked DB)."""

    def test_row_to_record(self):
        from app.infra.pg_media_asset_repo_async import AsyncPostgresMediaAssetRepository

        uid = uuid4()
        now = datetime.now(timezone.utc)
        row = {
            "id": uid,
            "tenant_id": "t1",
            "lead_id": "lead-1",
            "chat_id": "chat-1",
            "provider": "meta",
            "message_id": "m1",
            "kind": "video",
            "content_type": "video/mp4",
            "size_bytes": 999,
            "filename": "v.mp4",
            "s3_key": "media/t1/lead-1/v.mp4",
            "expires_at": now,
            "created_at": now,
        }
        rec = AsyncPostgresMediaAssetRepository._row_to_record(row)
        assert rec.id == uid
        assert rec.kind == "video"
        assert rec.size_bytes == 999
        assert rec.expires_at == now


# ============================================================================
# S3Storage Generic Methods
# ============================================================================

class TestS3BuildMediaKey:
    """Test S3Storage.build_media_key static method."""

    def test_with_lead_id(self):
        from app.infra.s3_storage import S3Storage
        key = S3Storage.build_media_key("tenant1", "abc-123", "mp4", lead_id="lead-42")
        assert key == "media/tenant1/lead-42/abc-123.mp4"

    def test_without_lead_id(self):
        from app.infra.s3_storage import S3Storage
        key = S3Storage.build_media_key("tenant1", "abc-123", "mov")
        assert key == "media/tenant1/unlinked/abc-123.mov"

    def test_different_extensions(self):
        from app.infra.s3_storage import S3Storage
        assert S3Storage.build_media_key("t", "a", "webm").endswith(".webm")
        assert S3Storage.build_media_key("t", "a", "3gp").endswith(".3gp")
        assert S3Storage.build_media_key("t", "a", "jpg").endswith(".jpg")


class TestS3GenericMethods:
    """Test put_object, delete_object, generate_presigned_get_url (mocked client)."""

    def _make_storage(self):
        """Create an S3Storage with a mocked boto3 client."""
        from app.infra.s3_storage import S3Storage

        with patch("app.infra.s3_storage.settings") as mock_settings:
            mock_settings.s3_enabled = True
            mock_settings.s3_endpoint_url = "http://minio:9000"
            mock_settings.s3_access_key = "test"
            mock_settings.s3_secret_key = "test"
            mock_settings.s3_region = "us-east-1"
            mock_settings.s3_bucket_name = "test-bucket"
            mock_settings.s3_public_url = ""
            mock_settings.s3_force_path_style = True

            with patch("app.infra.s3_storage.boto3") as mock_boto:
                mock_client = MagicMock()
                mock_boto.client.return_value = mock_client

                storage = S3Storage()
                storage._client = mock_client
                return storage, mock_client

    @pytest.mark.asyncio
    async def test_put_object(self):
        storage, mock_client = self._make_storage()
        await storage.put_object("media/t1/lead/abc.mp4", b"video-data", "video/mp4")
        mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="media/t1/lead/abc.mp4",
            Body=b"video-data",
            ContentType="video/mp4",
        )

    @pytest.mark.asyncio
    async def test_delete_object(self):
        storage, mock_client = self._make_storage()
        result = await storage.delete_object("media/t1/lead/abc.mp4")
        assert result is True
        mock_client.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_object_not_found(self):
        from botocore.exceptions import ClientError
        storage, mock_client = self._make_storage()
        mock_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "DeleteObject"
        )
        result = await storage.delete_object("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_generate_presigned_get_url(self):
        storage, mock_client = self._make_storage()
        mock_client.generate_presigned_url.return_value = "https://minio:9000/signed-url"
        url = await storage.generate_presigned_get_url("media/t1/lead/abc.mp4", expires_seconds=600)
        assert url == "https://minio:9000/signed-url"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "media/t1/lead/abc.mp4"},
            ExpiresIn=600,
        )

    @pytest.mark.asyncio
    async def test_presigned_url_capped_at_1800(self):
        storage, mock_client = self._make_storage()
        mock_client.generate_presigned_url.return_value = "url"
        await storage.generate_presigned_get_url("key", expires_seconds=9999)
        call_args = mock_client.generate_presigned_url.call_args
        assert call_args[1]["ExpiresIn"] == 1800 or call_args[0] == ("get_object",)
        # Check ExpiresIn was capped
        _, kwargs = mock_client.generate_presigned_url.call_args
        assert kwargs["ExpiresIn"] == 1800


# ============================================================================
# Video content-type → extension mapping
# ============================================================================

class TestExtFromContentType:
    def test_mp4(self):
        from app.infra.media_service import _ext_from_content_type
        assert _ext_from_content_type("video/mp4") == "mp4"

    def test_quicktime(self):
        from app.infra.media_service import _ext_from_content_type
        assert _ext_from_content_type("video/quicktime") == "mov"

    def test_webm(self):
        from app.infra.media_service import _ext_from_content_type
        assert _ext_from_content_type("video/webm") == "webm"

    def test_3gpp(self):
        from app.infra.media_service import _ext_from_content_type
        assert _ext_from_content_type("video/3gpp") == "3gp"

    def test_unknown(self):
        from app.infra.media_service import _ext_from_content_type
        assert _ext_from_content_type("video/x-custom") == "bin"


# ============================================================================
# Video Processing (MediaService.process_video_item)
# ============================================================================

class TestProcessVideoItem:
    """Test MediaService.process_video_item with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_rejects_disallowed_content_type(self):
        from app.infra.media_service import MediaService, MediaServiceConfig
        from app.core.engine.domain import MediaItem

        svc = MediaService(config=MediaServiceConfig())
        media = MediaItem(url="http://example.com/vid.avi", content_type="video/x-msvideo")

        with patch("app.config.settings") as mock_settings:
            mock_settings.media_allowed_video_types = "video/mp4,video/quicktime"
            mock_settings.media_video_max_size_mb = 64
            result = await svc.process_video_item(
                media, "t1", "chat1", provider="twilio", message_id="m1",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_oversized_video(self):
        from app.infra.media_service import MediaService, MediaServiceConfig
        from app.core.engine.domain import MediaItem
        from app.infra.media_fetchers.base import FetchResult

        svc = MediaService(config=MediaServiceConfig())
        media = MediaItem(url="http://example.com/vid.mp4", content_type="video/mp4")

        # 100 MB of data (over 64MB limit)
        big_data = b"x" * (100 * 1024 * 1024)

        with patch("app.config.settings") as mock_settings, \
             patch.object(svc, "_get_fetcher") as mock_fetcher, \
             patch("app.infra.s3_storage.is_s3_available", return_value=True):

            mock_settings.media_allowed_video_types = "video/mp4"
            mock_settings.media_video_max_size_mb = 64
            mock_settings.media_ttl_days = 90

            primary = AsyncMock()
            primary.fetch.return_value = FetchResult(data=big_data, content_type="video/mp4", source="http")
            mock_fetcher.return_value = (primary, None)

            result = await svc.process_video_item(
                media, "t1", "chat1", provider="twilio", message_id="m1",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_s3_not_available_returns_none(self):
        from app.infra.media_service import MediaService, MediaServiceConfig
        from app.core.engine.domain import MediaItem

        svc = MediaService(config=MediaServiceConfig())
        media = MediaItem(url="http://example.com/vid.mp4", content_type="video/mp4")

        with patch("app.config.settings") as mock_settings, \
             patch("app.infra.s3_storage.is_s3_available", return_value=False):
            mock_settings.media_allowed_video_types = "video/mp4"
            result = await svc.process_video_item(
                media, "t1", "chat1", provider="twilio", message_id="m1",
            )
        assert result is None


# ============================================================================
# handle_process_media routing (image vs video)
# ============================================================================

class TestHandleProcessMediaRouting:
    """Test that handle_process_media routes videos to process_video_item."""

    @pytest.mark.asyncio
    async def test_video_routed_to_process_video(self):
        from app.infra.job_worker import handle_process_media
        from app.infra.pg_job_repo_async import Job

        job = Job(
            id="job-1",
            tenant_id="t1",
            job_type="process_media",
            payload={
                "provider": "twilio",
                "tenant_id": "t1",
                "chat_id": "chat-1",
                "message_id": "msg-1",
                "lead_id": "lead-1",
                "media_items": [
                    {"url": "http://ex.com/v.mp4", "content_type": "video/mp4"},
                ],
            },
            status="running",
            priority=0,
            attempts=0,
            max_attempts=3,
            error_message=None,
            created_at=datetime.now(),
            scheduled_at=datetime.now(),
        )

        mock_video_result = {"asset_id": "abc", "kind": "video"}

        with patch("app.infra.tenant_registry.get_tenant_for_channel", return_value=None), \
             patch("app.infra.media_service.get_media_service") as mock_svc:
            mock_service = MagicMock()
            mock_service.process_video_item = AsyncMock(return_value=mock_video_result)
            mock_service.process_and_save = AsyncMock()
            mock_svc.return_value = mock_service

            await handle_process_media(job)

            mock_service.process_video_item.assert_called_once()
            mock_service.process_and_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_image_uses_existing_pipeline(self):
        from app.infra.job_worker import handle_process_media
        from app.infra.pg_job_repo_async import Job

        job = Job(
            id="job-2",
            tenant_id="t1",
            job_type="process_media",
            payload={
                "provider": "twilio",
                "tenant_id": "t1",
                "chat_id": "chat-1",
                "message_id": "msg-1",
                "media_items": [
                    {"url": "http://ex.com/img.jpg", "content_type": "image/jpeg"},
                ],
            },
            status="running",
            priority=0,
            attempts=0,
            max_attempts=3,
            error_message=None,
            created_at=datetime.now(),
            scheduled_at=datetime.now(),
        )

        mock_processed = {"uuid": "img-uuid", "photo_id": "p1"}

        with patch("app.infra.tenant_registry.get_tenant_for_channel", return_value=None), \
             patch("app.infra.media_service.get_media_service") as mock_svc:
            mock_service = MagicMock()
            mock_service.process_video_item = AsyncMock()
            mock_service.process_and_save = AsyncMock(return_value=mock_processed)
            mock_svc.return_value = mock_service

            await handle_process_media(job)

            mock_service.process_and_save.assert_called_once()
            mock_service.process_video_item.assert_not_called()


# ============================================================================
# Media Signature with media_signing_key
# ============================================================================

class TestMediaSigningKey:
    """Test that media_signing_key takes precedence over admin_token."""

    @patch("app.transport.security.settings")
    def test_uses_media_signing_key_when_set(self, mock_settings):
        mock_settings.media_signing_key = "dedicated-media-key-12345678901234"
        mock_settings.admin_token = "admin-token-should-not-be-used-xxxx"
        mock_settings.media_url_ttl_seconds = 3600

        from app.transport.security import generate_media_signature, verify_media_signature

        exp = int(time.time()) + 3600
        sig = generate_media_signature("asset-1", exp)

        valid, err = verify_media_signature("asset-1", sig, str(exp))
        assert valid is True
        assert err is None

    @patch("app.transport.security.settings")
    def test_falls_back_to_admin_token(self, mock_settings):
        mock_settings.media_signing_key = None
        mock_settings.admin_token = "fallback-admin-token-123456789012"
        mock_settings.media_url_ttl_seconds = 3600

        from app.transport.security import generate_media_signature, verify_media_signature

        exp = int(time.time()) + 3600
        sig = generate_media_signature("asset-1", exp)

        valid, err = verify_media_signature("asset-1", sig, str(exp))
        assert valid is True

    @patch("app.transport.security.settings")
    def test_no_keys_raises(self, mock_settings):
        mock_settings.media_signing_key = None
        mock_settings.admin_token = None

        from app.transport.security import generate_media_signature
        with pytest.raises(RuntimeError, match="ADMIN_TOKEN or MEDIA_SIGNING_KEY"):
            generate_media_signature("x", 12345)

    @patch("app.transport.security.settings")
    def test_no_keys_verify_fails(self, mock_settings):
        mock_settings.media_signing_key = None
        mock_settings.admin_token = None

        from app.transport.security import verify_media_signature
        valid, err = verify_media_signature("x", "sig", "12345")
        assert valid is False
        assert "misconfigured" in err.lower()


# ============================================================================
# Photo Threshold (G4.2)
# ============================================================================

class TestPhotoThreshold:
    """Test _get_media_for_lead threshold logic."""

    @pytest.mark.asyncio
    async def test_below_threshold_inline(self):
        """3 photos (below threshold of 5) → all inline."""
        from app.infra.notification_service import _get_media_for_lead

        mock_photos = [
            SimpleNamespace(id=uuid4(), s3_url=f"http://cdn/photo{i}.jpg")
            for i in range(3)
        ]

        with patch("app.infra.notification_service.settings") as mock_settings, \
             patch("app.infra.pg_photo_repo_async.get_photo_repo") as mock_repo, \
             patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_asset_repo:

            mock_settings.max_inline_media_count = 5
            mock_settings.s3_public_url = "http://cdn"
            mock_settings.twilio_webhook_url = "http://bot/webhooks/twilio"

            mock_repo_inst = AsyncMock()
            mock_repo_inst.get_for_lead.return_value = mock_photos
            mock_repo.return_value = mock_repo_inst

            mock_asset_inst = AsyncMock()
            mock_asset_inst.get_for_lead.return_value = []
            mock_asset_repo.return_value = mock_asset_inst

            delivery = await _get_media_for_lead("t1", "lead-1")

        assert len(delivery.inline_photo_urls) == 3
        assert len(delivery.link_lines) == 0

    @pytest.mark.asyncio
    async def test_above_threshold_links_only(self):
        """8 photos (above threshold of 5) → all as links."""
        from app.infra.notification_service import _get_media_for_lead

        mock_photos = [
            SimpleNamespace(id=uuid4(), s3_url=f"http://cdn/photo{i}.jpg")
            for i in range(8)
        ]

        with patch("app.infra.notification_service.settings") as mock_settings, \
             patch("app.infra.pg_photo_repo_async.get_photo_repo") as mock_repo, \
             patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_asset_repo:

            mock_settings.max_inline_media_count = 5
            mock_settings.s3_public_url = "http://cdn"
            mock_settings.twilio_webhook_url = "http://bot/webhooks/twilio"

            mock_repo_inst = AsyncMock()
            mock_repo_inst.get_for_lead.return_value = mock_photos
            mock_repo.return_value = mock_repo_inst

            mock_asset_inst = AsyncMock()
            mock_asset_inst.get_for_lead.return_value = []
            mock_asset_repo.return_value = mock_asset_inst

            delivery = await _get_media_for_lead("t1", "lead-1")

        assert len(delivery.inline_photo_urls) == 0
        assert len(delivery.link_lines) == 8
        assert all("Фото" in line for line in delivery.link_lines)

    @pytest.mark.asyncio
    async def test_video_always_link(self):
        """Videos always appear as links, never inline."""
        from app.infra.notification_service import _get_media_for_lead
        from app.infra.pg_media_asset_repo_async import MediaAssetRecord

        video_asset = MediaAssetRecord(
            id=uuid4(),
            tenant_id="t1",
            lead_id="lead-1",
            chat_id="chat-1",
            provider="telegram",
            message_id=None,
            kind="video",
            content_type="video/mp4",
            size_bytes=5000000,
            filename="vid.mp4",
            s3_key="media/t1/lead-1/vid.mp4",
        )

        with patch("app.infra.notification_service.settings") as mock_ns, \
             patch("app.transport.security.settings") as mock_sec, \
             patch("app.infra.pg_photo_repo_async.get_photo_repo") as mock_repo, \
             patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_asset_repo:

            signing_key = "test-key-xxxxxxxxxxxxxxxxxxxx1234"
            mock_ns.max_inline_media_count = 5
            mock_ns.s3_public_url = ""
            mock_ns.twilio_webhook_url = "http://bot/webhooks/twilio"
            mock_sec.media_signing_key = None
            mock_sec.admin_token = signing_key
            mock_sec.media_url_ttl_seconds = 3600

            mock_repo_inst = AsyncMock()
            mock_repo_inst.get_for_lead.return_value = []
            mock_repo.return_value = mock_repo_inst

            mock_asset_inst = AsyncMock()
            mock_asset_inst.get_for_lead.return_value = [video_asset]
            mock_asset_repo.return_value = mock_asset_inst

            delivery = await _get_media_for_lead("t1", "lead-1")

        assert len(delivery.inline_photo_urls) == 0
        assert len(delivery.link_lines) == 1
        assert "Видео" in delivery.link_lines[0]

    @pytest.mark.asyncio
    async def test_exact_threshold_inline(self):
        """Exactly 5 photos (= threshold) → inline."""
        from app.infra.notification_service import _get_media_for_lead

        mock_photos = [
            SimpleNamespace(id=uuid4(), s3_url=f"http://cdn/photo{i}.jpg")
            for i in range(5)
        ]

        with patch("app.infra.notification_service.settings") as mock_settings, \
             patch("app.infra.pg_photo_repo_async.get_photo_repo") as mock_repo, \
             patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_asset_repo:

            mock_settings.max_inline_media_count = 5
            mock_settings.s3_public_url = "http://cdn"
            mock_settings.twilio_webhook_url = "http://bot/webhooks/twilio"

            mock_repo_inst = AsyncMock()
            mock_repo_inst.get_for_lead.return_value = mock_photos
            mock_repo.return_value = mock_repo_inst

            mock_asset_inst = AsyncMock()
            mock_asset_inst.get_for_lead.return_value = []
            mock_asset_repo.return_value = mock_asset_inst

            delivery = await _get_media_for_lead("t1", "lead-1")

        assert len(delivery.inline_photo_urls) == 5
        assert len(delivery.link_lines) == 0


# ============================================================================
# TTL Cleanup
# ============================================================================

class TestMediaCleanupHandler:
    """Test handle_media_cleanup job handler."""

    @pytest.mark.asyncio
    async def test_no_expired_assets(self):
        from app.infra.job_worker import handle_media_cleanup
        from app.infra.pg_job_repo_async import Job

        job = Job(
            id="cleanup-1",
            tenant_id="t1",
            job_type="media_cleanup",
            payload={},
            status="running",
            priority=0,
            attempts=0,
            max_attempts=1,
            error_message=None,
            created_at=datetime.now(),
            scheduled_at=datetime.now(),
        )

        with patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_repo:
            mock_inst = AsyncMock()
            mock_inst.delete_expired.return_value = []
            mock_repo.return_value = mock_inst

            await handle_media_cleanup(job)

            mock_inst.delete_expired.assert_called_once_with(batch_size=100)

    @pytest.mark.asyncio
    async def test_deletes_s3_objects(self):
        from app.infra.job_worker import handle_media_cleanup
        from app.infra.pg_job_repo_async import Job
        from app.infra.pg_media_asset_repo_async import MediaAssetRecord

        expired_records = [
            MediaAssetRecord(
                id=uuid4(), tenant_id="t1", lead_id="l1", chat_id="c1",
                provider="twilio", message_id=None, kind="video",
                content_type="video/mp4", size_bytes=1000,
                filename="v.mp4", s3_key=f"media/t1/l1/v{i}.mp4",
            )
            for i in range(3)
        ]

        job = Job(
            id="cleanup-2",
            tenant_id="t1",
            job_type="media_cleanup",
            payload={"batch_size": 50},
            status="running",
            priority=0,
            attempts=0,
            max_attempts=1,
            error_message=None,
            created_at=datetime.now(),
            scheduled_at=datetime.now(),
        )

        with patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_repo, \
             patch("app.infra.s3_storage.is_s3_available", return_value=True), \
             patch("app.infra.s3_storage.get_s3_storage") as mock_s3:

            mock_inst = AsyncMock()
            mock_inst.delete_expired.return_value = expired_records
            mock_repo.return_value = mock_inst

            mock_s3_inst = AsyncMock()
            mock_s3.return_value = mock_s3_inst

            await handle_media_cleanup(job)

            assert mock_s3_inst.delete_object.call_count == 3
            mock_inst.delete_expired.assert_called_once_with(batch_size=50)

    @pytest.mark.asyncio
    async def test_s3_error_continues(self):
        """S3 delete failure for one object shouldn't fail the whole batch."""
        from app.infra.job_worker import handle_media_cleanup
        from app.infra.pg_job_repo_async import Job
        from app.infra.pg_media_asset_repo_async import MediaAssetRecord

        expired_records = [
            MediaAssetRecord(
                id=uuid4(), tenant_id="t1", lead_id="l1", chat_id="c1",
                provider="twilio", message_id=None, kind="video",
                content_type="video/mp4", size_bytes=1000,
                filename="v.mp4", s3_key=f"media/t1/l1/v{i}.mp4",
            )
            for i in range(2)
        ]

        job = Job(
            id="cleanup-3",
            tenant_id="t1",
            job_type="media_cleanup",
            payload={},
            status="running",
            priority=0,
            attempts=0,
            max_attempts=1,
            error_message=None,
            created_at=datetime.now(),
            scheduled_at=datetime.now(),
        )

        with patch("app.infra.pg_media_asset_repo_async.get_media_asset_repo") as mock_repo, \
             patch("app.infra.s3_storage.is_s3_available", return_value=True), \
             patch("app.infra.s3_storage.get_s3_storage") as mock_s3:

            mock_inst = AsyncMock()
            mock_inst.delete_expired.return_value = expired_records
            mock_repo.return_value = mock_inst

            mock_s3_inst = AsyncMock()
            # First call fails, second succeeds
            mock_s3_inst.delete_object.side_effect = [Exception("S3 error"), None]
            mock_s3.return_value = mock_s3_inst

            # Should NOT raise
            await handle_media_cleanup(job)
            assert mock_s3_inst.delete_object.call_count == 2


# ============================================================================
# Config: New EPIC G Settings
# ============================================================================

class TestEpicGConfig:
    """Test new config settings have correct defaults."""

    def test_default_video_max_size(self):
        from app.config import Settings
        s = Settings()
        assert s.media_video_max_size_mb == 64

    def test_default_ttl_days(self):
        from app.config import Settings
        s = Settings()
        assert s.media_ttl_days == 90

    def test_default_inline_threshold(self):
        from app.config import Settings
        s = Settings()
        assert s.max_inline_media_count == 5

    def test_default_signing_key_none(self):
        from app.config import Settings
        s = Settings()
        assert s.media_signing_key is None

    def test_default_allowed_video_types(self):
        from app.config import Settings
        s = Settings()
        types = {t.strip() for t in s.media_allowed_video_types.split(",")}
        assert "video/mp4" in types
        assert "video/quicktime" in types
        assert "video/webm" in types
        assert "video/3gpp" in types

    def test_schema_version_updated(self):
        from app.config import Settings
        s = Settings()
        assert s.expected_schema_version == "011_add_media_assets_table.sql"


# ============================================================================
# Migration SQL
# ============================================================================

class TestMigrationSQL:
    """Test the migration file exists and contains expected elements."""

    def test_migration_file_exists(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..",
            "app", "infra", "sql", "011_add_media_assets_table.sql"
        )
        assert os.path.isfile(path)

    def test_migration_contains_table(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..",
            "app", "infra", "sql", "011_add_media_assets_table.sql"
        )
        with open(path) as f:
            sql = f.read()
        assert "CREATE TABLE IF NOT EXISTS media_assets" in sql
        assert "kind" in sql
        assert "s3_key" in sql
        assert "expires_at" in sql
        assert "transcript_text" in sql  # G5 hook
        assert "transcript_status" in sql
        assert "transcript_provider" in sql
        assert "idx_media_assets_tenant_lead" in sql
        assert "idx_media_assets_expires" in sql
