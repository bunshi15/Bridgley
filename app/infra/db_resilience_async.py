# app/infra/db_resilience_async.py
"""
Async database resilience utilities.
Retry logic and circuit breaker for asyncpg.
"""
from __future__ import annotations
import time
import asyncio
from typing import TypeVar, Callable, Any
from contextlib import asynccontextmanager
from functools import wraps

import asyncpg
from app.infra.db_async import db_conn
from app.infra.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def is_transient_error(exc: Exception) -> bool:
    """
    Check if database error is transient (should retry).

    Transient errors:
    - Connection errors
    - Server closed connection
    - Too many connections
    - Deadlock
    """
    error_message = str(exc).lower()

    transient_patterns = [
        "connection",
        "timeout",
        "closed",
        "network",
        "deadlock",
        "too many connections",
        "server closed",
        "connection reset",
    ]

    # Check asyncpg-specific exceptions
    if isinstance(exc, asyncpg.PostgresConnectionError):
        return True

    if isinstance(exc, asyncpg.TooManyConnectionsError):
        return True

    if isinstance(exc, asyncpg.DeadlockDetectedError):
        return True

    # Check error message
    return any(pattern in error_message for pattern in transient_patterns)


def retry_on_transient_error(
    max_retries: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
    max_delay: float = 5.0
):
    """
    Decorator to retry async function on transient database errors.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries (seconds)
        backoff_factor: Multiplier for delay after each retry
        max_delay: Maximum delay between retries (seconds)

    Example:
        @retry_on_transient_error(max_retries=3)
        async def get_user(user_id: int):
            async with db_conn() as conn:
                return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc

                    # Check if error is transient
                    if not is_transient_error(exc):
                        logger.error(
                            f"Non-transient error in {func.__name__}: {exc}",
                            exc_info=True
                        )
                        raise

                    # Check if we've exhausted retries
                    if attempt >= max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded in {func.__name__}",
                            exc_info=True
                        )
                        raise

                    # Log retry
                    logger.warning(
                        f"Transient error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {exc}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    # Wait before retry
                    await asyncio.sleep(delay)

                    # Exponential backoff
                    delay = min(delay * backoff_factor, max_delay)

            # Should never reach here, but just in case
            raise last_exception

        return wrapper
    return decorator


@asynccontextmanager
async def safe_db_conn(autocommit: bool = True):
    """
    Safe database connection with automatic retry on transient errors.

    Usage:
        async with safe_db_conn() as conn:
            result = await conn.fetch("SELECT * FROM users WHERE id = $1", user_id)

    This wraps db_conn() with retry logic.
    """
    max_retries = 3
    delay = 0.1
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            async with db_conn(autocommit=autocommit) as conn:
                yield conn
                return  # Success
        except Exception as exc:
            last_exception = exc

            if not is_transient_error(exc):
                raise

            if attempt >= max_retries:
                logger.error(f"Max retries ({max_retries}) exceeded getting connection")
                raise

            logger.warning(
                f"Transient error getting connection (attempt {attempt + 1}/{max_retries}): {exc}. "
                f"Retrying in {delay:.2f}s..."
            )

            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 5.0)

    raise last_exception


# Circuit breaker state
class CircuitBreaker:
    """
    Simple circuit breaker for database connections.

    States:
    - CLOSED: Normal operation
    - OPEN: Too many failures, reject requests
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        name: str = "default"
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.name = name

        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def is_available(self) -> bool:
        """Check if circuit breaker allows requests"""
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if timeout expired
            if time.time() - self.last_failure_time >= self.timeout:
                logger.info(f"Circuit breaker '{self.name}' entering HALF_OPEN state")
                self.state = "HALF_OPEN"
                return True
            return False

        # HALF_OPEN state
        return True

    def record_success(self):
        """Record successful operation"""
        if self.state == "HALF_OPEN":
            logger.info(f"Circuit breaker '{self.name}' closing (recovered)")
            self.state = "CLOSED"
        self.failure_count = 0

    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != "OPEN":
                logger.error(
                    f"Circuit breaker '{self.name}' opening "
                    f"(failures: {self.failure_count}/{self.failure_threshold})"
                )
                self.state = "OPEN"


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    timeout=60.0,
    name="database"
)


@asynccontextmanager
async def protected_db_conn(autocommit: bool = True):
    """
    Database connection with circuit breaker protection.

    Prevents cascading failures by rejecting requests when database is down.

    Usage:
        async with protected_db_conn() as conn:
            result = await conn.fetch("SELECT * FROM users")
    """
    # Check circuit breaker
    if not _circuit_breaker.is_available():
        raise RuntimeError("Circuit breaker is OPEN (database unavailable)")

    try:
        async with safe_db_conn(autocommit=autocommit) as conn:
            yield conn
            _circuit_breaker.record_success()
    except Exception as exc:
        _circuit_breaker.record_failure()
        raise
