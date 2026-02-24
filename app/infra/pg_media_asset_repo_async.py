# app/infra/pg_media_asset_repo_async.py
"""
Async media asset repository for generic media storage (EPIC G).

Stores metadata for all media types (image, video, audio, document).
Binary data lives in S3; this table holds only metadata + S3 keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from app.infra.db_resilience_async import safe_db_conn
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


@dataclass
class MediaAssetRecord:
    """Media asset record from database."""
    id: UUID
    tenant_id: str
    lead_id: Optional[str]
    chat_id: str
    provider: str
    message_id: Optional[str]
    kind: str               # 'image' | 'video' | 'audio' | 'document'
    content_type: str
    size_bytes: int
    filename: str
    s3_key: str
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class AsyncPostgresMediaAssetRepository:
    """
    Async media asset repository.

    All binary data lives in S3. This repository manages metadata rows
    in the ``media_assets`` table.
    """

    async def save(
        self,
        tenant_id: str,
        chat_id: str,
        provider: str,
        kind: str,
        content_type: str,
        size_bytes: int,
        filename: str,
        s3_key: str,
        *,
        lead_id: Optional[str] = None,
        message_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> UUID:
        """Save a media asset record. Returns the asset ID (UUID)."""
        asset_id = uuid4()

        try:
            async with safe_db_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO media_assets(
                        id, tenant_id, lead_id, chat_id, provider, message_id,
                        kind, content_type, size_bytes, filename, s3_key, expires_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    asset_id,
                    tenant_id,
                    lead_id,
                    chat_id,
                    provider,
                    message_id,
                    kind,
                    content_type,
                    size_bytes,
                    filename,
                    s3_key,
                    expires_at,
                )

            logger.info(
                "Media asset saved: id=%s, kind=%s, tenant=%s, size=%d",
                str(asset_id)[:8], kind, tenant_id, size_bytes,
            )
            inc_counter("media_assets_saved", tenant_id=tenant_id, kind=kind)
            return asset_id

        except Exception:
            logger.error(
                "Failed to save media asset: tenant=%s, chat=%s***",
                tenant_id, chat_id[:6],
                exc_info=True,
            )
            inc_counter("media_assets_save_failed", tenant_id=tenant_id)
            raise

    async def get_by_id(self, asset_id: UUID) -> Optional[MediaAssetRecord]:
        """Get a media asset by ID."""
        try:
            async with safe_db_conn() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, tenant_id, lead_id, chat_id, provider, message_id,
                           kind, content_type, size_bytes, filename, s3_key,
                           expires_at, created_at
                    FROM media_assets
                    WHERE id = $1
                    """,
                    asset_id,
                )
                if not row:
                    return None
                return self._row_to_record(row)

        except Exception:
            logger.error("Failed to get media asset: id=%s", asset_id, exc_info=True)
            raise

    async def get_for_lead(
        self,
        tenant_id: str,
        lead_id: str,
        limit: int = 50,
    ) -> list[MediaAssetRecord]:
        """Get media assets for a specific lead (ordered by creation time)."""
        try:
            async with safe_db_conn() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, lead_id, chat_id, provider, message_id,
                           kind, content_type, size_bytes, filename, s3_key,
                           expires_at, created_at
                    FROM media_assets
                    WHERE tenant_id = $1 AND lead_id = $2
                    ORDER BY created_at ASC
                    LIMIT $3
                    """,
                    tenant_id,
                    lead_id,
                    limit,
                )
                return [self._row_to_record(r) for r in rows]

        except Exception:
            logger.error(
                "Failed to get media assets for lead: tenant=%s, lead=%s***",
                tenant_id, lead_id[:8],
                exc_info=True,
            )
            raise

    async def link_to_lead(
        self,
        tenant_id: str,
        chat_id: str,
        lead_id: str,
    ) -> int:
        """Link all unlinked media assets from a chat to a lead."""
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    """
                    UPDATE media_assets
                    SET lead_id = $3
                    WHERE tenant_id = $1 AND chat_id = $2 AND lead_id IS NULL
                    """,
                    tenant_id,
                    chat_id,
                    lead_id,
                )
                updated = int(result.split()[-1]) if result else 0
                if updated > 0:
                    logger.info("Linked %d media assets to lead: %s", updated, lead_id[:8])
                return updated

        except Exception:
            logger.error("Failed to link media assets: lead_id=%s", lead_id[:8], exc_info=True)
            raise

    async def delete_expired(self, batch_size: int = 100) -> list[MediaAssetRecord]:
        """
        Find and delete expired media assets.

        Returns the deleted records so the caller can clean up S3 objects.
        Idempotent: safe to call repeatedly.
        """
        try:
            async with safe_db_conn() as conn:
                rows = await conn.fetch(
                    """
                    DELETE FROM media_assets
                    WHERE id IN (
                        SELECT id FROM media_assets
                        WHERE expires_at IS NOT NULL AND expires_at < now()
                        LIMIT $1
                    )
                    RETURNING id, tenant_id, lead_id, chat_id, provider, message_id,
                              kind, content_type, size_bytes, filename, s3_key,
                              expires_at, created_at
                    """,
                    batch_size,
                )
                records = [self._row_to_record(r) for r in rows]
                if records:
                    logger.info("Deleted %d expired media assets", len(records))
                    inc_counter("media_assets_expired_deleted", count=len(records))
                return records

        except Exception:
            logger.error("Failed to delete expired media assets", exc_info=True)
            raise

    @staticmethod
    def _row_to_record(row) -> MediaAssetRecord:
        return MediaAssetRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            lead_id=row["lead_id"],
            chat_id=row["chat_id"],
            provider=row["provider"],
            message_id=row["message_id"],
            kind=row["kind"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            filename=row["filename"],
            s3_key=row["s3_key"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )


# Global instance
_media_asset_repo: AsyncPostgresMediaAssetRepository | None = None


def get_media_asset_repo() -> AsyncPostgresMediaAssetRepository:
    """Get the global media asset repository instance."""
    global _media_asset_repo
    if _media_asset_repo is None:
        _media_asset_repo = AsyncPostgresMediaAssetRepository()
    return _media_asset_repo
