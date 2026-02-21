# app/infra/pg_inbound_repo_async.py
"""
Async PostgreSQL inbound message repository (asyncpg).
Handles idempotency tracking for incoming messages.
"""
from __future__ import annotations
from app.core.ports import AsyncInboundMessageRepository
from app.infra.db_resilience_async import safe_db_conn
from app.infra.metrics import AppMetrics
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class AsyncPostgresInboundMessageRepository(AsyncInboundMessageRepository):
    """Async PostgreSQL implementation of InboundMessageRepository using asyncpg."""

    async def seen_or_mark(self, tenant_id: str, provider: str, message_id: str, chat_id: str) -> bool:
        """
        Check if message was already seen, or mark it as seen.

        Args:
            tenant_id: Tenant identifier
            provider: Provider name (e.g., "twilio")
            message_id: Unique message ID from provider
            chat_id: Chat identifier

        Returns:
            True => already seen (idempotency hit)
            False => first time, marked as seen
        """
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    """
                    INSERT INTO inbound_messages(tenant_id, provider, message_id, chat_id)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (tenant_id, provider, message_id) DO NOTHING
                    """,
                    tenant_id,
                    provider,
                    message_id,
                    chat_id,
                )

                # Parse result: "INSERT 0 1" → inserted, "INSERT 0 0" → conflict (already seen)
                row_count = 0
                if result and result.startswith("INSERT"):
                    row_count = int(result.split()[-1])

                already_seen = row_count == 0

                if already_seen:
                    logger.info(f"Idempotency hit: provider={provider}, message_id={message_id}")
                    AppMetrics.idempotency_hit(tenant_id, provider)

                return already_seen

        except Exception as exc:
            logger.error(
                f"Failed to check/mark inbound message: provider={provider}, message_id={message_id}",
                exc_info=True
            )
            AppMetrics.database_error("inbound_seen_or_mark")
            raise

    async def delete_for_chat(self, tenant_id: str, provider: str, chat_id: str) -> int:
        """
        Delete all inbound messages for a chat.

        Args:
            tenant_id: Tenant identifier
            provider: Provider name
            chat_id: Chat identifier

        Returns:
            Number of deleted messages
        """
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM inbound_messages
                    WHERE tenant_id=$1 AND provider=$2 AND chat_id=$3
                    """,
                    tenant_id,
                    provider,
                    chat_id,
                )

                # Parse result: "DELETE N"
                deleted = 0
                if result and result.startswith("DELETE"):
                    deleted = int(result.split()[-1])

                if deleted > 0:
                    logger.info(f"Deleted {deleted} inbound messages for chat={chat_id[:6]}***")

                return deleted

        except Exception as exc:
            logger.error(f"Failed to delete inbound messages for chat={chat_id[:6]}***", exc_info=True)
            AppMetrics.database_error("inbound_delete_for_chat")
            raise

    async def cleanup_old(self, ttl_days: int = 30) -> int:
        """
        Delete inbound message records older than ``ttl_days``.

        Prevents unbounded growth of the idempotency table.
        Safe to run periodically — old records no longer serve a
        deduplication purpose.

        Returns:
            Number of deleted rows.
        """
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM inbound_messages
                    WHERE received_at < now() - ($1 || ' days')::interval
                    """,
                    str(ttl_days),
                )

                deleted = 0
                if result and result.startswith("DELETE"):
                    deleted = int(result.split()[-1])

                if deleted > 0:
                    logger.info(f"Inbound idempotency cleanup: deleted {deleted} rows older than {ttl_days}d")

                return deleted

        except Exception as exc:
            logger.error("Failed to cleanup old inbound messages", exc_info=True)
            AppMetrics.database_error("inbound_cleanup_old")
            raise
