# app/infra/rate_limiter.py
from __future__ import annotations
import time
from collections import defaultdict
from threading import Lock
from typing import Optional
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window.

    ⚠️ NOT horizontally scalable: each process holds its own window,
    so with N replicas the effective limit is N × max_requests.
    TODO: Replace with Redis-backed limiter (ZRANGEBYSCORE sliding window)
          when scaling beyond a single process.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> tuple[bool, Optional[int]]:
        """
        Check if request is allowed for the given key.

        Returns:
            (allowed, retry_after_seconds)
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            # Clean old requests
            self._requests[key] = [
                ts for ts in self._requests[key] if ts > cutoff
            ]

            request_count = len(self._requests[key])

            if request_count >= self.max_requests:
                # Calculate when the oldest request will expire
                oldest = min(self._requests[key])
                retry_after = int(oldest + self.window_seconds - now) + 1

                # Mask key to avoid logging phone numbers / PII
                masked = key[:4] + "***" if len(key) > 4 else "***"
                logger.warning(
                    "Rate limit exceeded for key=%s", masked,
                    extra={
                        "key_masked": masked,
                        "count": request_count,
                        "limit": self.max_requests,
                        "retry_after": retry_after,
                    }
                )
                return False, retry_after

            # Record this request
            self._requests[key].append(now)
            return True, None

    def get_usage(self, key: str) -> dict:
        """Get current usage stats for a key"""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            recent = [ts for ts in self._requests[key] if ts > cutoff]
            return {
                "count": len(recent),
                "limit": self.max_requests,
                "window_seconds": self.window_seconds,
                "remaining": max(0, self.max_requests - len(recent)),
            }

    def cleanup(self, max_age_seconds: int = 3600) -> int:
        """
        Remove keys that haven't been used recently.
        Returns number of keys removed.
        """
        now = time.time()
        cutoff = now - max_age_seconds

        with self._lock:
            to_remove = []
            for key, timestamps in self._requests.items():
                if not timestamps or max(timestamps) < cutoff:
                    to_remove.append(key)

            for key in to_remove:
                del self._requests[key]

            if to_remove:
                logger.info(f"Rate limiter cleanup: removed {len(to_remove)} keys")

            return len(to_remove)


# Dependency for FastAPI
from fastapi import Request, HTTPException, status


class RateLimitDependency:
    """FastAPI dependency for rate limiting"""

    def __init__(self, limiter: InMemoryRateLimiter):
        self.limiter = limiter

    async def __call__(self, request: Request) -> None:
        # Use client IP as the key
        # In production behind proxy, use X-Forwarded-For
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # Allow health checks to bypass rate limiting
        if request.url.path in ["/health", "/ready"]:
            return

        allowed, retry_after = self.limiter.is_allowed(client_ip)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)} if retry_after else None,
            )