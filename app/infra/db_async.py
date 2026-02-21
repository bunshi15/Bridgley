# app/infra/db_async.py
"""
Async database connection using asyncpg.
Drop-in replacement for db.py with async/await support.
"""
from __future__ import annotations
import os
from typing import AsyncContextManager
from contextlib import asynccontextmanager

import asyncpg
from app.config import settings
from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# Global connection pool
_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Initialize connection pool on startup"""
    global _pool

    if _pool is not None:
        return

    logger.info("Initializing asyncpg connection pool")

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.pg_pool_min,
        max_size=settings.pg_pool_max,
        command_timeout=60,
        # Connection parameters
        server_settings={
            'application_name': 'stage0_bot',
        }
    )

    logger.info(f"Connection pool created: min={settings.pg_pool_min}, max={settings.pg_pool_max}")


async def close_pool() -> None:
    """Close connection pool on shutdown"""
    global _pool

    if _pool is None:
        return

    logger.info("Closing connection pool")
    await _pool.close()
    _pool = None
    logger.info("Connection pool closed")


@asynccontextmanager
async def db_conn(autocommit: bool = True) -> AsyncContextManager[asyncpg.Connection]:
    """
    Get database connection from pool (async).

    Usage:
        async with db_conn() as conn:
            result = await conn.fetch("SELECT * FROM users WHERE id = $1", user_id)

    Args:
        autocommit: If True (default), commits automatically. If False, you must commit/rollback.

    Yields:
        asyncpg.Connection
    """
    global _pool

    if _pool is None:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")

    # Acquire connection from pool
    conn = await _pool.acquire()

    try:
        if not autocommit:
            # Start transaction
            transaction = conn.transaction()
            await transaction.start()

            try:
                yield conn
                await transaction.commit()
            except Exception:
                await transaction.rollback()
                raise
        else:
            # Autocommit mode (no explicit transaction)
            yield conn
    finally:
        # Release connection back to pool
        await _pool.release(conn)


async def get_pool() -> asyncpg.Pool:
    """Get the connection pool directly (for advanced usage)"""
    global _pool
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    return _pool
