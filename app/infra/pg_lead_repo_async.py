# app/infra/pg_lead_repo_async.py
"""
Async PostgreSQL lead repository (asyncpg).
Stores finalized lead data.
"""
from __future__ import annotations
import json
from typing import Any

from app.core.ports import AsyncLeadRepository
from app.infra.db_resilience_async import safe_db_conn
from app.infra.logging_config import get_logger
from app.infra.metrics import AppMetrics

logger = get_logger(__name__)


class AsyncPostgresLeadRepository(AsyncLeadRepository):
    """Async PostgreSQL implementation of LeadRepository using asyncpg."""

    async def save_lead(
        self,
        tenant_id: str,
        lead_id: str,
        chat_id: str,
        payload: dict[str, Any]
    ) -> None:
        """
        Save finalized lead to database.

        Args:
            tenant_id: Tenant identifier
            lead_id: Unique lead identifier
            chat_id: Chat identifier
            payload: Lead data (JSON-serializable dict)

        Note:
            Uses INSERT ... ON CONFLICT DO NOTHING to prevent duplicate leads.
        """
        async with safe_db_conn() as conn:
            # Convert dict to JSON string for asyncpg
            payload_json = json.dumps(payload)

            result = await conn.execute(
                """
                INSERT INTO leads (tenant_id, lead_id, chat_id, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (tenant_id, lead_id) DO NOTHING
                """,
                tenant_id,
                lead_id,
                chat_id,
                payload_json
            )

            # Parse result string: "INSERT 0 1" → 1 row inserted, "INSERT 0 0" → conflict (no insert)
            # asyncpg returns string like "INSERT 0 N" where N is row count
            if result and result.startswith("INSERT"):
                row_count = int(result.split()[-1])
                if row_count > 0:
                    AppMetrics.lead_created(tenant_id)
                    logger.info(
                        f"Lead created: tenant={tenant_id}, lead_id={lead_id}, chat_id={chat_id}"
                    )
                else:
                    logger.debug(
                        f"Lead already exists (conflict): tenant={tenant_id}, lead_id={lead_id}"
                    )
