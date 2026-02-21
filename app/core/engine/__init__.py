# app/core/engine/__init__.py
"""
Core engine -- provider-agnostic domain logic.

This package contains the pure domain models, abstract protocols (ports),
bot type system, handler registry, and the application-level use-case
orchestrator (Stage0Engine).

Canonical imports:
    from app.core.engine import Stage0Engine, UniversalEngine
    from app.core.engine.domain import SessionState, InboundMessage
    from app.core.engine.ports import AsyncSessionStore
"""
from app.core.engine.domain import (  # noqa: F401
    Step,
    LeadData,
    SessionState,
    MediaItem,
    InboundMessage,
)
from app.core.engine.ports import (  # noqa: F401
    AsyncSessionStore,
    AsyncLeadRepository,
    AsyncInboundMessageRepository,
    AsyncLeadFinalizer,
)
from app.core.engine.bot_types import (  # noqa: F401
    Intent,
    MessageType,
    BotConfig,
    BotRegistry,
    Translator,
    Translation,
    IntentPatterns,
    detect_universal_intent,
)
from app.core.engine.bot_handler import BotHandler, BotHandlerRegistry  # noqa: F401
from app.core.engine.universal_engine import UniversalEngine  # noqa: F401
from app.core.engine.use_cases import Stage0Engine  # noqa: F401
