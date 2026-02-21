# app/infra/media_fetchers/base.py
"""
Media fetcher abstraction layer.

Defines the protocol and shared types for provider-specific media fetchers.
Each fetcher is responsible only for downloading raw bytes — image processing
and validation remain in image_processor.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from app.core.domain import MediaItem


class MediaFetchError(Exception):
    """
    Base error for media fetch failures.

    Attributes:
        retryable: Whether the caller should attempt a fallback or retry.
    """

    def __init__(self, message: str, retryable: bool = True):
        self.retryable = retryable
        super().__init__(message)


@dataclass
class FetchResult:
    """Result of a media fetch operation."""

    data: bytes
    content_type: Optional[str] = None
    source: str = ""  # e.g. "twilio_api", "meta_api", "http_direct"


class MediaFetcher(Protocol):
    """Protocol for provider-specific media fetchers."""

    async def fetch(
        self,
        media_item: MediaItem,
        message_id: str,
    ) -> FetchResult:
        """
        Download media and return raw bytes.

        Args:
            media_item: MediaItem with URL and/or provider-specific IDs.
            message_id: Provider message ID (e.g. Twilio MessageSid).

        Returns:
            FetchResult with raw bytes and content type.

        Raises:
            MediaFetchError: If download fails after all internal retries.
        """
        ...
