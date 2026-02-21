# app/infra/health_checks_async.py
from __future__ import annotations
import time
from typing import Dict, Any
from enum import Enum

from app.infra.db_async import get_pool
from app.infra.logging_config import get_logger
from app.infra.schema_validator import get_schema_info

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class AsyncHealthCheck:
    """Base class for async health checks"""

    def __init__(self, name: str, critical: bool = True):
        self.name = name
        self.critical = critical

    async def check(self) -> Dict[str, Any]:
        """
        Perform health check.
        Returns dict with 'status', 'details', and optionally 'error'
        """
        raise NotImplementedError


class AsyncDatabaseHealthCheck(AsyncHealthCheck):
    """Check database connectivity and basic operations"""

    def __init__(self):
        super().__init__("database", critical=True)

    async def check(self) -> Dict[str, Any]:
        start = time.time()

        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Test basic query
                result = await conn.fetchval("SELECT 1")

                if result != 1:
                    return {
                        "status": HealthStatus.UNHEALTHY,
                        "details": "Unexpected query result",
                        "error": f"Expected 1, got {result}"
                    }

                # Check required tables exist
                required_tables = ["sessions", "leads", "inbound_messages"]
                missing_tables = []

                for table in required_tables:
                    table_exists = await conn.fetchval("SELECT to_regclass($1)", table)
                    if table_exists is None:
                        missing_tables.append(table)

                if missing_tables:
                    return {
                        "status": HealthStatus.UNHEALTHY,
                        "details": "Missing required tables",
                        "error": f"Missing: {', '.join(missing_tables)}"
                    }

                # Check query performance
                duration = time.time() - start
                if duration > 1.0:
                    return {
                        "status": HealthStatus.DEGRADED,
                        "details": f"Slow database response: {duration:.3f}s",
                        "response_time": duration
                    }

                return {
                    "status": HealthStatus.HEALTHY,
                    "details": "Database operational",
                    "response_time": duration
                }

        except Exception as exc:
            logger.error("Database health check failed", exc_info=True)
            return {
                "status": HealthStatus.UNHEALTHY,
                "details": "Database connection failed",
                "error": str(exc)[:200]
            }


class AsyncSessionStoreHealthCheck(AsyncHealthCheck):
    """Check session store operations"""

    def __init__(self):
        super().__init__("session_store", critical=True)

    async def check(self) -> Dict[str, Any]:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Check if we can read from sessions table
                await conn.fetchval("SELECT COUNT(*) FROM sessions LIMIT 1")

                # Check recent activity
                recent_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM sessions WHERE updated_at > now() - interval '1 hour'"
                )

                return {
                    "status": HealthStatus.HEALTHY,
                    "details": "Session store operational",
                    "active_sessions_1h": recent_count
                }

        except Exception as exc:
            logger.error("Session store health check failed", exc_info=True)
            return {
                "status": HealthStatus.UNHEALTHY,
                "details": "Session store check failed",
                "error": str(exc)[:200]
            }


class AsyncLeadRepositoryHealthCheck(AsyncHealthCheck):
    """Check lead repository operations"""

    def __init__(self):
        super().__init__("lead_repository", critical=False)

    async def check(self) -> Dict[str, Any]:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Check if we can read from leads table
                total_leads = await conn.fetchval("SELECT COUNT(*) FROM leads LIMIT 1")

                # Check recent leads
                recent_leads = await conn.fetchval(
                    "SELECT COUNT(*) FROM leads WHERE created_at > now() - interval '24 hours'"
                )

                return {
                    "status": HealthStatus.HEALTHY,
                    "details": "Lead repository operational",
                    "total_leads": total_leads,
                    "leads_24h": recent_leads
                }

        except Exception as exc:
            logger.error("Lead repository health check failed", exc_info=True)
            return {
                "status": HealthStatus.DEGRADED,
                "details": "Lead repository check failed",
                "error": str(exc)[:200]
            }


class AsyncHealthChecker:
    """Aggregate async health checks"""

    def __init__(self):
        self.checks: list[AsyncHealthCheck] = [
            AsyncDatabaseHealthCheck(),
            AsyncSessionStoreHealthCheck(),
            AsyncLeadRepositoryHealthCheck(),
        ]

    async def run_checks(self, include_non_critical: bool = True) -> Dict[str, Any]:
        """
        Run all health checks.

        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "checks": {...},
                "schema": {...},
                "timestamp": float
            }
        """
        results = {}
        overall_status = HealthStatus.HEALTHY

        for check in self.checks:
            if not include_non_critical and not check.critical:
                continue

            result = await check.check()
            results[check.name] = result

            # Determine overall status
            if result["status"] == HealthStatus.UNHEALTHY and check.critical:
                overall_status = HealthStatus.UNHEALTHY
            elif result["status"] == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                overall_status = HealthStatus.DEGRADED

        # Add schema information (useful for debugging)
        schema_info = await get_schema_info()

        return {
            "status": overall_status.value,
            "checks": results,
            "schema": schema_info,
            "timestamp": time.time()
        }


# Global async health checker instance
_async_health_checker = AsyncHealthChecker()


def get_async_health_checker() -> AsyncHealthChecker:
    """Get the global async health checker"""
    return _async_health_checker
