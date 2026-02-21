# app/infra/s3_storage.py
"""
S3-compatible storage service for photos.

Supports:
- AWS S3
- Cloudflare R2
- MinIO (for testing)
- Any S3-compatible storage

Configuration:

PRODUCTION (public cloud bucket):
    S3_ENDPOINT_URL=https://s3.amazonaws.com (or R2 endpoint)
    S3_PUBLIC_URL=https://cdn.example.com/bucket (public/CDN URL)
    S3_BUCKET_NAME=your-bucket
    S3_ACCESS_KEY=...
    S3_SECRET_KEY=...
    -> Photos served via redirect to S3_PUBLIC_URL (fast, CDN-ready)

TESTING (internal MinIO):
    S3_ENDPOINT_URL=http://minio:9000
    S3_PUBLIC_URL= (empty - no public URL)
    S3_BUCKET_NAME=stage0
    S3_ACCESS_KEY=minioadmin
    S3_SECRET_KEY=minioadmin
    -> Photos proxied through /media endpoint using authenticated S3 client
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


class S3Storage:
    """S3-compatible storage for photos."""

    def __init__(self):
        if not settings.s3_enabled:
            raise RuntimeError("S3 storage not configured")

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
                s3={"addressing_style": "path" if settings.s3_force_path_style else "virtual"}
            ),
        )
        self._bucket = settings.s3_bucket_name
        self._public_url = settings.s3_public_url

        logger.info(
            f"S3 storage initialized: bucket={self._bucket}, "
            f"endpoint={settings.s3_endpoint_url}"
        )

    def _get_key(self, tenant_id: str, photo_id: str, ext: str = "jpg") -> str:
        """Generate S3 key for a photo."""
        return f"photos/{tenant_id}/{photo_id}.{ext}"

    def get_public_url(self, tenant_id: str, photo_id: str, ext: str = "jpg") -> str:
        """
        Get public URL for a photo.

        IMPORTANT: If S3_PUBLIC_URL is not set, returns the internal endpoint URL.
        This is stored in the database, so:
        - For public S3 (AWS, R2): set S3_PUBLIC_URL to the public URL
        - For internal MinIO: leave S3_PUBLIC_URL empty, use /media proxy
        """
        key = self._get_key(tenant_id, photo_id, ext)

        if self._public_url:
            # Use configured public URL (CDN, R2 public bucket, etc.)
            return f"{self._public_url.rstrip('/')}/{key}"
        else:
            # Construct from endpoint (internal URL - will be proxied via /media)
            return f"{settings.s3_endpoint_url.rstrip('/')}/{self._bucket}/{key}"

    def get_internal_url(self, tenant_id: str, photo_id: str, ext: str = "jpg") -> str:
        """
        Get internal URL for fetching from S3 (for proxying).
        Always uses S3_ENDPOINT_URL regardless of S3_PUBLIC_URL setting.
        """
        key = self._get_key(tenant_id, photo_id, ext)
        return f"{settings.s3_endpoint_url.rstrip('/')}/{self._bucket}/{key}"

    async def upload(
        self,
        photo_id: str,
        tenant_id: str,
        data: bytes,
        content_type: str = "image/jpeg",
        ext: str = "jpg",
    ) -> str:
        """
        Upload a photo to S3.

        Args:
            photo_id: Unique photo ID (UUID)
            tenant_id: Tenant identifier
            data: Photo binary data
            content_type: MIME type
            ext: File extension

        Returns:
            Public URL of the uploaded photo
        """
        key = self._get_key(tenant_id, photo_id, ext)

        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000",  # 1 year cache
            )

            public_url = self.get_public_url(tenant_id, photo_id, ext)

            logger.info(
                f"Photo uploaded to S3: id={photo_id}, tenant={tenant_id}, "
                f"size={len(data)}, key={key}"
            )
            inc_counter("s3_uploads_success", tenant_id=tenant_id)

            return public_url

        except ClientError as e:
            logger.error(
                f"S3 upload failed: id={photo_id}, tenant={tenant_id}, error={e}",
                exc_info=True,
            )
            inc_counter("s3_uploads_failed", tenant_id=tenant_id)
            raise

    async def download(
        self,
        tenant_id: str,
        photo_id: str,
        ext: str = "jpg",
    ) -> Optional[bytes]:
        """
        Download a photo from S3.

        Returns:
            Photo binary data, or None if not found
        """
        key = self._get_key(tenant_id, photo_id, ext)

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            data = response["Body"].read()
            return data

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error(f"S3 download failed: key={key}, error={e}", exc_info=True)
            raise

    async def delete(
        self,
        tenant_id: str,
        photo_id: str,
        ext: str = "jpg",
    ) -> bool:
        """
        Delete a photo from S3.

        Returns:
            True if deleted, False if not found
        """
        key = self._get_key(tenant_id, photo_id, ext)

        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.info(f"Photo deleted from S3: key={key}")
            return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return False
            logger.error(f"S3 delete failed: key={key}, error={e}", exc_info=True)
            raise

    async def exists(
        self,
        tenant_id: str,
        photo_id: str,
        ext: str = "jpg",
    ) -> bool:
        """Check if a photo exists in S3."""
        key = self._get_key(tenant_id, photo_id, ext)

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False


# Global instance (lazy initialization)
_s3_storage: S3Storage | None = None


def get_s3_storage() -> S3Storage:
    """Get the global S3 storage instance."""
    global _s3_storage
    if _s3_storage is None:
        _s3_storage = S3Storage()
    return _s3_storage


def is_s3_available() -> bool:
    """Check if S3 storage is configured and available."""
    return settings.s3_enabled
