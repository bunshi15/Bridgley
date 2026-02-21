#!/usr/bin/env python3
# app/infra/migrate.py
"""
Standalone migration runner.

Run migrations separately from application startup:
    python -m app.infra.migrate

This script should be run:
- In CI/CD before deployment
- As a separate Kubernetes Job/init container
- Manually before starting the application
- In a dedicated "migrate" container in docker-compose

The application will validate schema version at startup but NOT run migrations.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.infra.migrations_async import apply_migrations
from app.infra.db_async import init_pool, close_pool
from app.infra.logging_config import setup_logging, get_logger
from app.config import settings

# Initialize logging
setup_logging(level="INFO", use_json=False)
logger = get_logger(__name__)


async def main():
    """Run migrations"""
    logger.info("=" * 60)
    logger.info("Database Migration Runner")
    logger.info("=" * 60)
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Database: {settings.pghost}:{settings.pgport}/{settings.pgdatabase}")
    logger.info("=" * 60)

    try:
        # Initialize database pool
        logger.info("Initializing database connection...")
        await init_pool()
        logger.info("✓ Database connected")

        # Apply migrations
        logger.info("\nApplying migrations...")
        result = await apply_migrations()

        # Show results
        logger.info("\n" + "=" * 60)
        logger.info("Migration Results")
        logger.info("=" * 60)
        logger.info(f"Status: {'SUCCESS' if result['ok'] else 'FAILED'}")
        logger.info(f"Migrations applied: {result['count']}")

        if result['applied']:
            logger.info("\nApplied migrations:")
            for migration in result['applied']:
                logger.info(f"  ✓ {migration}")
        else:
            logger.info("\nNo new migrations to apply")

        logger.info("=" * 60)

        # Close pool
        await close_pool()

        return 0 if result['ok'] else 1

    except Exception as exc:
        logger.critical(f"\n{'=' * 60}")
        logger.critical("MIGRATION FAILED")
        logger.critical(f"{'=' * 60}")
        logger.critical(f"Error: {exc}", exc_info=True)
        logger.critical(f"{'=' * 60}")

        try:
            await close_pool()
        except:
            pass

        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
