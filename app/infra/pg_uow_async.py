# app/infra/pg_uow_async.py
"""
Async PostgreSQL lead finalizer (asyncpg).
Atomically saves lead and deletes session in a transaction.
Also notifies operator via WhatsApp when lead is completed.
"""
from __future__ import annotations
import json
from typing import Any

from app.core.ports import AsyncLeadFinalizer
from app.infra.db_resilience_async import safe_db_conn
from app.infra.metrics import AppMetrics
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class AsyncPostgresLeadFinalizer(AsyncLeadFinalizer):
    """Async PostgreSQL implementation of LeadFinalizer using asyncpg."""

    async def finalize(self, tenant_id: str, lead_id: str, chat_id: str, payload: dict[str, Any]) -> None:
        """
        Atomically save the lead and delete the session.

        Uses a transaction to ensure both operations succeed or fail together.

        Args:
            tenant_id: Tenant identifier
            lead_id: Unique lead identifier
            chat_id: Chat identifier
            payload: Lead data (JSON-serializable dict)

        Raises:
            Exception: If either operation fails (transaction will be rolled back)
        """
        try:
            async with safe_db_conn(autocommit=False) as conn:
                # Start transaction (handled by safe_db_conn with autocommit=False)

                # Insert/update lead — retrieve sequential lead number
                row = await conn.fetchrow(
                    """
                    INSERT INTO leads(tenant_id, lead_id, chat_id, payload_json)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ON CONFLICT (tenant_id, lead_id)
                    DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()
                    RETURNING lead_seq
                    """,
                    tenant_id,
                    lead_id,
                    chat_id,
                    json.dumps(payload),
                )
                # Store sequential number in payload for crew/operator message
                if row:
                    try:
                        lead_seq = row["lead_seq"]
                        if lead_seq is not None:
                            data = payload.get("data", payload)
                            data.setdefault("custom", {})["lead_number"] = int(lead_seq)
                    except (KeyError, TypeError):
                        pass  # Column not yet added (pre-010 migration)

                # Delete session
                await conn.execute(
                    "DELETE FROM sessions WHERE tenant_id=$1 AND chat_id=$2",
                    tenant_id,
                    chat_id,
                )

                # Link photos to this lead (photos saved during this conversation)
                # Only links photos with:
                # - lead_id=NULL (unlinked)
                # - created_at within last 2 hours (current session, not old orphaned photos)
                result = await conn.execute(
                    """
                    UPDATE photos
                    SET lead_id = $3
                    WHERE tenant_id = $1
                      AND chat_id = $2
                      AND lead_id IS NULL
                      AND created_at > NOW() - INTERVAL '2 hours'
                    """,
                    tenant_id,
                    chat_id,
                    lead_id,
                )
                # Parse "UPDATE N" result
                linked_count = int(result.split()[-1]) if result else 0
                logger.info(
                    f"Lead finalize: linked {linked_count} new photos to lead {lead_id}",
                    extra={"lead_id": lead_id, "photos_linked": linked_count}
                )

                # Transaction auto-commits on exit from context manager

                logger.info(f"Lead finalized: lead_id={lead_id}, chat={chat_id[:6]}***")
                AppMetrics.lead_created(tenant_id)

            # Enqueue operator notification as a durable job
            from app.infra.pg_job_repo_async import get_job_repo
            job_repo = get_job_repo()
            await job_repo.enqueue(
                tenant_id=tenant_id,
                job_type="notify_operator",
                payload={
                    "lead_id": lead_id,
                    "chat_id": chat_id,
                    "payload": payload,
                },
                priority=-1,
                max_attempts=5,
            )

            # Dispatch Layer Iteration 1: enqueue crew fallback if enabled
            from app.infra.tenant_registry import get_dispatch_config
            dispatch_cfg = get_dispatch_config(tenant_id)
            if dispatch_cfg["crew_fallback_enabled"]:
                await job_repo.enqueue(
                    tenant_id=tenant_id,
                    job_type="notify_crew_fallback",
                    payload={
                        "lead_id": lead_id,
                        "payload": payload,
                        "idempotency_key": f"{lead_id}:crew_fallback_v1",
                    },
                    priority=0,   # Lower priority than full lead notification
                    max_attempts=3,
                    delay_seconds=2,  # Small delay so full lead arrives first
                )

        except Exception as exc:
            logger.error(
                f"Failed to finalize lead: lead_id={lead_id}, chat={chat_id[:6]}***",
                exc_info=True
            )
            AppMetrics.database_error("lead_finalize")
            raise
