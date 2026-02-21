# app/infra/outbound_queue.py
"""
Outbound message queue with rate limiting and retry logic.

Handles Twilio rate limits (429 errors) by:
1. Queuing outbound messages
2. Rate limiting sends (configurable messages per second)
3. Automatic retry with exponential backoff
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine
from collections import deque

from app.config import settings
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


@dataclass
class OutboundMessage:
    """Message waiting to be sent"""
    id: str
    to: str
    body: str
    media_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    next_retry_at: float = 0


class OutboundQueue:
    """
    Queue for outbound messages with rate limiting and retry.

    Rate limit: 1 message per second by default (Twilio sandbox limit).
    Production Twilio accounts have higher limits.
    """

    def __init__(
        self,
        messages_per_second: float = 1.0,
        max_retries: int = 3,
        base_retry_delay: float = 5.0,  # seconds
    ):
        self._queue: deque[OutboundMessage] = deque()
        self._messages_per_second = messages_per_second
        self._min_interval = 1.0 / messages_per_second
        self._max_retries = max_retries
        self._base_retry_delay = base_retry_delay
        self._last_send_time: float = 0
        self._lock = asyncio.Lock()
        self._processing = False
        self._send_func: Callable[[OutboundMessage], Coroutine[Any, Any, bool]] | None = None

    def set_send_function(
        self,
        func: Callable[[OutboundMessage], Coroutine[Any, Any, bool]]
    ) -> None:
        """Set the function that actually sends messages"""
        self._send_func = func

    async def enqueue(self, message: OutboundMessage) -> None:
        """Add a message to the queue"""
        async with self._lock:
            self._queue.append(message)
            logger.info(
                f"Message queued: id={message.id}, to={message.to[:6]}***, "
                f"queue_size={len(self._queue)}"
            )
            inc_counter("outbound_queued")

    async def process_queue(self) -> None:
        """Process queued messages with rate limiting"""
        if self._send_func is None:
            logger.error("Send function not set")
            return

        if self._processing:
            return

        self._processing = True

        try:
            while True:
                message = await self._get_next_message()
                if message is None:
                    break

                # Rate limiting: wait if needed
                await self._wait_for_rate_limit()

                # Try to send
                success = await self._try_send(message)

                if not success:
                    # Schedule retry if attempts remaining
                    if message.attempts < self._max_retries:
                        message.attempts += 1
                        delay = self._base_retry_delay * (2 ** (message.attempts - 1))
                        message.next_retry_at = time.time() + delay

                        async with self._lock:
                            self._queue.append(message)

                        logger.info(
                            f"Message scheduled for retry: id={message.id}, "
                            f"attempt={message.attempts}, delay={delay}s"
                        )
                    else:
                        logger.error(
                            f"Message failed after {self._max_retries} attempts: "
                            f"id={message.id}, to={message.to[:6]}***"
                        )
                        inc_counter("outbound_failed_permanent")
        finally:
            self._processing = False

    async def _get_next_message(self) -> OutboundMessage | None:
        """Get next message ready to send"""
        async with self._lock:
            if not self._queue:
                return None

            now = time.time()

            # Find first message ready to send (not waiting for retry)
            for i, msg in enumerate(self._queue):
                if msg.next_retry_at <= now:
                    self._queue.remove(msg)
                    return msg

            # All messages are waiting for retry
            return None

    async def _wait_for_rate_limit(self) -> None:
        """Wait to respect rate limit"""
        now = time.time()
        elapsed = now - self._last_send_time

        if elapsed < self._min_interval:
            wait_time = self._min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

    async def _try_send(self, message: OutboundMessage) -> bool:
        """Try to send a message"""
        try:
            self._last_send_time = time.time()
            success = await self._send_func(message)

            if success:
                inc_counter("outbound_sent")
                logger.info(f"Message sent: id={message.id}, to={message.to[:6]}***")
            else:
                inc_counter("outbound_failed")

            return success

        except Exception as e:
            logger.error(f"Send error: id={message.id}, error={e}")
            inc_counter("outbound_error")
            return False

    @property
    def queue_size(self) -> int:
        """Current queue size"""
        return len(self._queue)

    async def flush(self) -> None:
        """Process all queued messages"""
        while self._queue:
            await self.process_queue()
            await asyncio.sleep(0.1)


# Global queue instance
_outbound_queue: OutboundQueue | None = None


def get_outbound_queue() -> OutboundQueue:
    """Get the global outbound queue instance with settings from config"""
    global _outbound_queue
    if _outbound_queue is None:
        _outbound_queue = OutboundQueue(
            messages_per_second=settings.outbound_messages_per_second,
            max_retries=settings.outbound_max_retries,
            base_retry_delay=settings.outbound_base_retry_delay,
        )
        logger.info(
            f"Outbound queue initialized: {settings.outbound_messages_per_second} msg/sec, "
            f"max_retries={settings.outbound_max_retries}, base_delay={settings.outbound_base_retry_delay}s"
        )
    return _outbound_queue
