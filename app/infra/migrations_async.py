# app/infra/migrations_async.py
"""
Async database migrations runner (asyncpg).
"""
from __future__ import annotations
from pathlib import Path

from app.infra.db_async import db_conn
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


def _sql_dir() -> Path:
    """Get SQL migrations directory path."""
    # Next to this file: app/infra/sql
    return Path(__file__).resolve().parent / "sql"


async def apply_migrations() -> dict:
    """
    Apply SQL migrations from app/infra/sql directory.

    Migrations are applied in alphabetical order (001_init.sql, 002_add_feature.sql, etc.).
    Already applied migrations are tracked in schema_migrations table.

    Returns:
        dict with keys:
            - ok: bool (True if successful)
            - applied: list[str] (migration filenames applied in this run)
            - count: int (number of migrations applied)
    """
    sql_dir = _sql_dir()
    files = sorted(p for p in sql_dir.glob("*.sql") if p.is_file())

    async with db_conn(autocommit=False) as conn:
        # Create migrations tracking table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations(
              version text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )

        # Get already applied migrations
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        applied = {row['version'] for row in rows}

        applied_now = []
        for p in files:
            version = p.name
            if version in applied:
                logger.debug(f"Migration {version} already applied, skipping")
                continue

            logger.info(f"Applying migration: {version}")
            sql = p.read_text(encoding="utf-8")

            # Execute migration SQL
            await conn.execute(sql)

            # Mark as applied
            await conn.execute(
                "INSERT INTO schema_migrations(version) VALUES ($1)",
                version
            )

            applied_now.append(version)
            logger.info(f"Migration {version} applied successfully")

        # Transaction auto-commits on exit

    logger.info(f"Migrations complete: {len(applied_now)} applied")
    return {"ok": True, "applied": applied_now, "count": len(applied_now)}
