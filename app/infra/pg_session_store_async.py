from __future__ import annotations
import json
from dataclasses import asdict
from typing import Optional

from app.core.domain import SessionState, LeadData
from app.core.ports import AsyncSessionStore
from app.infra.db_resilience_async import safe_db_conn
from app.infra.metrics import AppMetrics
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


def _get_step_value(step) -> str:
    """Get step value whether it's an enum or string"""
    return step.value if hasattr(step, 'value') else step


class AsyncPostgresSessionStore(AsyncSessionStore):
    """Async implementation of SessionStore using asyncpg"""

    async def get(self, tenant_id: str, chat_id: str) -> Optional[SessionState]:
        try:
            async with safe_db_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT state_json::text, updated_at FROM sessions WHERE tenant_id=$1 AND chat_id=$2",
                    tenant_id, chat_id
                )
                if not row:
                    return None

                state = json.loads(row['state_json'])
                # state_json stores full state
                data = state.get("data") or {}
                ld = LeadData(**data)
                st = SessionState(
                    tenant_id=state["tenant_id"],
                    chat_id=state["chat_id"],
                    lead_id=state["lead_id"],
                    step=state["step"],  # step is now a string
                    data=ld,
                    bot_type=state.get("bot_type", "moving_bot_v1"),
                    language=state.get("language", "ru"),
                    metadata=state.get("metadata", {}),
                    updated_at=row['updated_at'],
                )
                return st
        except Exception as exc:
            logger.error(f"Failed to get session: tenant={tenant_id}, chat={chat_id[:6]}***", exc_info=True)
            AppMetrics.database_error("session_get")
            raise

    async def upsert(self, state: SessionState) -> None:
        step_value = _get_step_value(state.step)
        payload = {
            "tenant_id": state.tenant_id,
            "chat_id": state.chat_id,
            "lead_id": state.lead_id,
            "step": step_value,
            "data": asdict(state.data),
            "bot_type": state.bot_type,
            "language": state.language,
            "metadata": state.metadata,
        }
        try:
            async with safe_db_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO sessions(tenant_id, chat_id, state_json, step)
                    VALUES ($1, $2, $3::jsonb, $4)
                    ON CONFLICT (tenant_id, chat_id)
                    DO UPDATE SET
                      state_json = EXCLUDED.state_json,
                      step = EXCLUDED.step,
                      updated_at = now()
                    """,
                    state.tenant_id, state.chat_id, json.dumps(payload), step_value
                )
        except Exception as exc:
            logger.error(f"Failed to upsert session: tenant={state.tenant_id}, chat={state.chat_id[:6]}***", exc_info=True)
            AppMetrics.database_error("session_upsert")
            raise

    async def delete(self, tenant_id: str, chat_id: str) -> None:
        try:
            async with safe_db_conn() as conn:
                await conn.execute(
                    "DELETE FROM sessions WHERE tenant_id=$1 AND chat_id=$2",
                    tenant_id, chat_id
                )
        except Exception as exc:
            logger.error(f"Failed to delete session: tenant={tenant_id}, chat={chat_id[:6]}***", exc_info=True)
            AppMetrics.database_error("session_delete")
            raise

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        try:
            async with safe_db_conn() as conn:
                result = await conn.execute(
                    "DELETE FROM sessions WHERE updated_at < now() - ($1 || ' seconds')::interval",
                    str(ttl_seconds)
                )
                # asyncpg execute returns "DELETE N" string
                deleted = int(result.split()[-1]) if result else 0
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired sessions (ttl={ttl_seconds}s)")
                return deleted
        except Exception as exc:
            logger.error(f"Failed to cleanup expired sessions: ttl={ttl_seconds}", exc_info=True)
            AppMetrics.database_error("session_cleanup")
            raise
