# app/core/engine/ports.py
from __future__ import annotations
from typing import Protocol, Optional
from app.core.engine.domain import SessionState


# ============================================================================
# ASYNC PROTOCOLS (Recommended - asyncpg based)
# ============================================================================

class AsyncSessionStore(Protocol):
    async def get(self, tenant_id: str, chat_id: str) -> Optional[SessionState]: ...
    async def upsert(self, state: SessionState) -> None: ...
    async def delete(self, tenant_id: str, chat_id: str) -> None: ...
    async def cleanup_expired(self, ttl_seconds: int) -> int: ...


class AsyncLeadRepository(Protocol):
    async def save_lead(self, tenant_id: str, lead_id: str, chat_id: str, payload: dict) -> None: ...


class AsyncInboundMessageRepository(Protocol):
    async def seen_or_mark(self, tenant_id: str, provider: str, message_id: str, chat_id: str) -> bool:
        """
        True  => message already seen (duplicate), skip processing
        False => first time seeing it, proceed with processing
        """
        ...

    async def delete_for_chat(self, tenant_id: str, provider: str, chat_id: str) -> int:
        ...


class AsyncLeadFinalizer(Protocol):
    async def finalize(self, tenant_id: str, lead_id: str, chat_id: str, payload: dict) -> None: ...
