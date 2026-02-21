# app/infra/schema_validator.py
"""
Schema version validator for production deployments.

The application does NOT run migrations itself. Instead:
1. Migrations run separately (CI/CD, migrate job, manual script)
2. Application validates schema version matches expected version
3. Application crashes if schema is incompatible

This prevents:
- Accidental schema changes in production
- Race conditions with multiple instances
- Security risks from automatic migrations
- Downtime from failed migrations during startup
"""
from __future__ import annotations
from app.config import settings
from app.infra.db_async import db_conn
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


async def validate_schema_version() -> dict:
    """
    Validate that database schema version matches expected version.

    Returns:
        dict with keys:
            - ok: bool (True if schema is compatible)
            - current_version: str | None (current schema version)
            - expected_version: str (expected schema version)
            - error: str | None (error message if validation failed)

    Raises:
        RuntimeError: If schema version is incompatible
    """
    async with db_conn() as conn:
        # Check if schema_migrations table exists
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'schema_migrations'
            )
            """
        )

        if not table_exists:
            error = (
                "Schema migrations table not found. "
                "Database has not been initialized. "
                "Run migrations first: python -m app.infra.migrate"
            )
            logger.critical(error)
            raise RuntimeError(error)

        # Get latest applied migration
        latest = await conn.fetchrow(
            """
            SELECT version, applied_at
            FROM schema_migrations
            ORDER BY applied_at DESC
            LIMIT 1
            """
        )

        if not latest:
            error = (
                "No migrations have been applied. "
                "Database is empty. "
                "Run migrations first: python -m app.infra.migrate"
            )
            logger.critical(error)
            raise RuntimeError(error)

        current_version = latest['version']

        # Check if current version matches expected
        if current_version != settings.expected_schema_version:
            error = (
                f"Schema version mismatch! "
                f"Expected: {settings.expected_schema_version}, "
                f"Found: {current_version}. "
                f"Run migrations to update schema: python -m app.infra.migrate"
            )
            logger.critical(
                error,
                extra={
                    "expected": settings.expected_schema_version,
                    "current": current_version,
                    "applied_at": latest['applied_at'].isoformat()
                }
            )
            raise RuntimeError(error)

        logger.info(
            f"Schema version validated: {current_version}",
            extra={
                "version": current_version,
                "applied_at": latest['applied_at'].isoformat()
            }
        )

        return {
            "ok": True,
            "current_version": current_version,
            "expected_version": settings.expected_schema_version,
            "error": None
        }


async def get_schema_info() -> dict:
    """
    Get information about current schema state.

    Returns:
        dict with schema information (for health checks, debugging)
    """
    async with db_conn() as conn:
        # Check if migrations table exists
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'schema_migrations'
            )
            """
        )

        if not table_exists:
            return {
                "initialized": False,
                "migrations_applied": 0,
                "latest_version": None
            }

        # Get all migrations
        rows = await conn.fetch(
            """
            SELECT version, applied_at
            FROM schema_migrations
            ORDER BY applied_at
            """
        )

        migrations = [
            {
                "version": row['version'],
                "applied_at": row['applied_at'].isoformat()
            }
            for row in rows
        ]

        return {
            "initialized": True,
            "migrations_applied": len(migrations),
            "latest_version": migrations[-1]['version'] if migrations else None,
            "expected_version": settings.expected_schema_version,
            "is_compatible": migrations[-1]['version'] == settings.expected_schema_version if migrations else False,
            "all_migrations": migrations
        }
