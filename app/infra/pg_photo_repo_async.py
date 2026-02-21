# app/infra/pg_photo_repo_async.py
"""
Async photo repository with S3 and database storage support.

Storage strategy:
- If S3 is configured: store binary data in S3, metadata in DB
- If S3 not configured: store everything in DB (fallback for dev)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from app.config import settings
from app.infra.db_resilience_async import safe_db_conn
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


@dataclass
class PhotoRecord:
    """Photo record from database"""
    id: UUID
    tenant_id: str
    chat_id: str
    lead_id: Optional[str]
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    s3_url: Optional[str] = None  # S3 public URL (if stored in S3)
    data: Optional[bytes] = None  # Binary data (if stored in DB)


class AsyncPostgresPhotoRepository:
    """
    Async photo repository with S3 support.

    When S3 is enabled:
    - Binary data stored in S3
    - Metadata (id, urls, dimensions) stored in PostgreSQL
    - data column is NULL in DB

    When S3 is disabled (dev mode):
    - Everything stored in PostgreSQL
    - s3_url is NULL in DB
    """

    def __init__(self):
        self._s3 = None
        if settings.s3_enabled:
            from app.infra.s3_storage import get_s3_storage
            self._s3 = get_s3_storage()
            logger.info("Photo repository using S3 storage")
        else:
            logger.info("Photo repository using database storage (S3 not configured)")

    async def save(
        self,
        tenant_id: str,
        chat_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        width: int,
        height: int,
        data: bytes,
        lead_id: Optional[str] = None,
    ) -> UUID:
        """
        Save a photo.

        If S3 is enabled: uploads to S3 and stores metadata in DB.
        If S3 is disabled: stores everything in DB.

        Returns the photo ID (UUID).
        """
        photo_id = uuid4()
        s3_url: Optional[str] = None
        db_data: Optional[bytes] = None

        # Determine extension from content type
        ext = "jpg"
        if content_type == "image/png":
            ext = "png"
        elif content_type == "image/webp":
            ext = "webp"

        try:
            if self._s3:
                # Upload to S3
                s3_url = await self._s3.upload(
                    photo_id=str(photo_id),
                    tenant_id=tenant_id,
                    data=data,
                    content_type=content_type,
                    ext=ext,
                )
            else:
                # Store in DB
                db_data = data

            # Save metadata to database
            async with safe_db_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO photos(id, tenant_id, chat_id, lead_id, filename,
                                       content_type, size_bytes, width, height, s3_url, data)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    photo_id,
                    tenant_id,
                    chat_id,
                    lead_id,
                    filename,
                    content_type,
                    size_bytes,
                    width,
                    height,
                    s3_url,
                    db_data,
                )

            storage_type = "S3" if self._s3 else "DB"
            logger.info(
                f"Photo saved ({storage_type}): id={photo_id}, tenant={tenant_id}, "
                f"chat={chat_id[:6]}***, size={size_bytes}"
            )
            inc_counter("photos_saved", tenant_id=tenant_id)
            return photo_id

        except Exception as exc:
            logger.error(
                f"Failed to save photo: tenant={tenant_id}, chat={chat_id[:6]}***",
                exc_info=True
            )
            inc_counter("photos_save_failed", tenant_id=tenant_id)
            raise

    async def get_by_id(self, photo_id: UUID) -> Optional[PhotoRecord]:
        """Get a photo by ID."""
        try:
            async with safe_db_conn() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, tenant_id, chat_id, lead_id, filename, content_type,
                           size_bytes, width, height, s3_url, data
                    FROM photos
                    WHERE id = $1
                    """,
                    photo_id,
                )
                if not row:
                    return None

                return PhotoRecord(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    chat_id=row["chat_id"],
                    lead_id=row["lead_id"],
                    filename=row["filename"],
                    content_type=row["content_type"],
                    size_bytes=row["size_bytes"],
                    width=row["width"],
                    height=row["height"],
                    s3_url=row["s3_url"],
                    data=row["data"],
                )

        except Exception as exc:
            logger.error(f"Failed to get photo: id={photo_id}", exc_info=True)
            raise

    async def get_latest_for_chat(
        self,
        tenant_id: str,
        chat_id: str,
        limit: int = 1,
    ) -> list[PhotoRecord]:
        """Get latest photos for a chat (metadata only, no binary data)."""
        try:
            async with safe_db_conn() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, chat_id, lead_id, filename, content_type,
                           size_bytes, width, height, s3_url
                    FROM photos
                    WHERE tenant_id = $1 AND chat_id = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    tenant_id,
                    chat_id,
                    limit,
                )
                return [
                    PhotoRecord(
                        id=row["id"],
                        tenant_id=row["tenant_id"],
                        chat_id=row["chat_id"],
                        lead_id=row["lead_id"],
                        filename=row["filename"],
                        content_type=row["content_type"],
                        size_bytes=row["size_bytes"],
                        width=row["width"],
                        height=row["height"],
                        s3_url=row["s3_url"],
                        data=None,  # Don't load binary data
                    )
                    for row in rows
                ]

        except Exception as exc:
            logger.error(
                f"Failed to get photos: tenant={tenant_id}, chat={chat_id[:6]}***",
                exc_info=True
            )
            raise

    async def get_for_lead(
        self,
        tenant_id: str,
        lead_id: str,
        limit: int = 10,
    ) -> list[PhotoRecord]:
        """
        Get photos for a specific lead/ticket (metadata only, no binary data).

        This is the correct method to use when sending notifications -
        only includes photos uploaded during this specific ticket.
        """
        try:
            async with safe_db_conn() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, chat_id, lead_id, filename, content_type,
                           size_bytes, width, height, s3_url
                    FROM photos
                    WHERE tenant_id = $1 AND lead_id = $2
                    ORDER BY created_at ASC
                    LIMIT $3
                    """,
                    tenant_id,
                    lead_id,
                    limit,
                )
                return [
                    PhotoRecord(
                        id=row["id"],
                        tenant_id=row["tenant_id"],
                        chat_id=row["chat_id"],
                        lead_id=row["lead_id"],
                        filename=row["filename"],
                        content_type=row["content_type"],
                        size_bytes=row["size_bytes"],
                        width=row["width"],
                        height=row["height"],
                        s3_url=row["s3_url"],
                        data=None,  # Don't load binary data
                    )
                    for row in rows
                ]

        except Exception as exc:
            logger.error(
                f"Failed to get photos for lead: tenant={tenant_id}, lead={lead_id[:8]}***",
                exc_info=True
            )
            raise

    async def link_to_lead(
        self,
        tenant_id: str,
        chat_id: str,
        lead_id: str,
    ) -> int:
        """Link all photos from a chat to a lead."""
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    """
                    UPDATE photos
                    SET lead_id = $3
                    WHERE tenant_id = $1 AND chat_id = $2 AND lead_id IS NULL
                    """,
                    tenant_id,
                    chat_id,
                    lead_id,
                )
                # asyncpg returns "UPDATE N"
                updated = int(result.split()[-1]) if result else 0
                if updated > 0:
                    logger.info(f"Linked {updated} photos to lead: {lead_id}")
                return updated

        except Exception as exc:
            logger.error(
                f"Failed to link photos: lead_id={lead_id}",
                exc_info=True
            )
            raise


# Global instance
_photo_repo: AsyncPostgresPhotoRepository | None = None


def get_photo_repo() -> AsyncPostgresPhotoRepository:
    """Get the global photo repository instance."""
    global _photo_repo
    if _photo_repo is None:
        _photo_repo = AsyncPostgresPhotoRepository()
    return _photo_repo
