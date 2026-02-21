# app/core/engine/bot_handler.py
"""
Bot Handler Protocol - defines the interface that all bot handlers must implement.
This allows the universal engine to work with any bot type.
"""
from __future__ import annotations
from typing import Protocol, Tuple, Optional
from app.core.engine.domain import SessionState
from app.core.engine.bot_types import BotConfig


class BotHandler(Protocol):
    """
    Protocol that all bot type handlers must implement.
    The universal engine delegates bot-specific logic to these handlers.
    """

    @property
    def config(self) -> BotConfig:
        """Return the bot configuration"""
        ...

    def new_session(self, tenant_id: str, chat_id: str, language: str = "ru") -> SessionState:
        """
        Create a new session for this bot type.

        Args:
            tenant_id: Tenant identifier
            chat_id: Chat/conversation identifier
            language: User's preferred language (default: "ru")

        Returns:
            New SessionState initialized for this bot type
        """
        ...

    def handle_text(
        self,
        state: SessionState,
        text: str
    ) -> Tuple[SessionState, str, bool]:
        """
        Process text input and update session state.

        Args:
            state: Current session state
            text: User's text input

        Returns:
            Tuple of (new_state, reply_text, is_done)
            - new_state: Updated session state
            - reply_text: Bot's reply message
            - is_done: True if conversation is complete
        """
        ...

    def handle_media(
        self,
        state: SessionState
    ) -> Tuple[SessionState, Optional[str]]:
        """
        Process media input and update session state.

        Args:
            state: Current session state

        Returns:
            Tuple of (new_state, reply_text)
            - new_state: Updated session state
            - reply_text: Optional reply message (None if no reply needed)
        """
        ...

    def handle_location(
        self,
        state: SessionState,
        latitude: float,
        longitude: float,
        name: str | None = None,
        address: str | None = None,
    ) -> Tuple[SessionState, str, bool]:
        """
        Process GPS location input and update session state (Phase 5).

        Default behavior: ignore the location and return a hint message.
        Bot handlers that support location should override this.

        Args:
            state: Current session state
            latitude: GPS latitude
            longitude: GPS longitude
            name: Optional place name
            address: Optional street address

        Returns:
            Tuple of (new_state, reply_text, is_done)
        """
        ...

    def get_payload(self, state: SessionState) -> dict:
        """
        Generate final payload for lead creation/notification.

        Args:
            state: Final session state

        Returns:
            Dictionary containing all collected lead data
        """
        ...


class BotHandlerRegistry:
    """
    Central registry for bot handlers.
    Maps bot_type strings to handler instances.
    """

    _handlers: dict[str, BotHandler] = {}

    @classmethod
    def register(cls, bot_type: str, handler: BotHandler) -> None:
        """Register a bot handler"""
        cls._handlers[bot_type] = handler

    @classmethod
    def get(cls, bot_type: str) -> Optional[BotHandler]:
        """Get bot handler by type"""
        return cls._handlers.get(bot_type)

    @classmethod
    def list_types(cls) -> list[str]:
        """List all registered bot types"""
        return list(cls._handlers.keys())

    @classmethod
    def has_handler(cls, bot_type: str) -> bool:
        """Check if handler is registered"""
        return bot_type in cls._handlers
