# app/core/engine/universal_engine.py
"""
Universal bot engine that works with any bot type.
Delegates bot-specific logic to registered BotHandlers.
"""
from __future__ import annotations
from typing import Tuple, Optional
from app.core.engine.domain import SessionState
from app.core.engine.bot_handler import BotHandlerRegistry, BotHandler


class UniversalEngine:
    """
    Universal conversation engine that works with any bot type.

    This engine provides the core conversation logic (state management, step transitions)
    while delegating bot-specific behavior to BotHandler implementations.
    """

    @staticmethod
    def get_handler(bot_type: str) -> BotHandler:
        """
        Get the bot handler for a given bot type.

        Args:
            bot_type: Bot type identifier (e.g., "moving_bot_v1")

        Returns:
            BotHandler instance

        Raises:
            ValueError: If bot_type is not registered
        """
        handler = BotHandlerRegistry.get(bot_type)
        if handler is None:
            available = BotHandlerRegistry.list_types()
            raise ValueError(
                f"Unknown bot type '{bot_type}'. "
                f"Available types: {', '.join(available) if available else 'none'}"
            )
        return handler

    @staticmethod
    def new_session(
        tenant_id: str,
        chat_id: str,
        bot_type: str = "moving_bot_v1",
        language: str = "ru"
    ) -> SessionState:
        """
        Create a new session for any bot type.

        Args:
            tenant_id: Tenant identifier
            chat_id: Chat identifier
            bot_type: Bot type identifier
            language: User's preferred language

        Returns:
            New SessionState for the specified bot type
        """
        handler = UniversalEngine.get_handler(bot_type)
        return handler.new_session(tenant_id, chat_id, language)

    @staticmethod
    def handle_text(
        state: SessionState,
        text: str
    ) -> Tuple[SessionState, str, bool]:
        """
        Process text input using the appropriate bot handler.

        Args:
            state: Current session state (contains bot_type)
            text: User's text input

        Returns:
            Tuple of (new_state, reply, is_done)
        """
        handler = UniversalEngine.get_handler(state.bot_type)
        return handler.handle_text(state, text)

    @staticmethod
    def handle_media(state: SessionState) -> Tuple[SessionState, Optional[str]]:
        """
        Process media input using the appropriate bot handler.

        Args:
            state: Current session state (contains bot_type)

        Returns:
            Tuple of (new_state, optional_reply)
        """
        handler = UniversalEngine.get_handler(state.bot_type)
        return handler.handle_media(state)

    @staticmethod
    def handle_location(
        state: SessionState,
        latitude: float,
        longitude: float,
        name: str | None = None,
        address: str | None = None,
    ) -> Tuple[SessionState, str, bool]:
        """
        Process GPS location using the appropriate bot handler (Phase 5).

        Args:
            state: Current session state (contains bot_type)
            latitude: GPS latitude
            longitude: GPS longitude
            name: Optional place name
            address: Optional street address

        Returns:
            Tuple of (new_state, reply, is_done)
        """
        handler = UniversalEngine.get_handler(state.bot_type)
        return handler.handle_location(state, latitude, longitude, name, address)

    @staticmethod
    def get_payload(state: SessionState) -> dict:
        """
        Generate payload for lead creation using the appropriate bot handler.

        Args:
            state: Final session state

        Returns:
            Dictionary containing bot-specific lead data
        """
        handler = UniversalEngine.get_handler(state.bot_type)
        return handler.get_payload(state)
