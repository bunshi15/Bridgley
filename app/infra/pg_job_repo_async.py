# app/infra/pg_job_repo_async.py
"""
Async PostgreSQL job repository (asyncpg).

DB-backed job queue with claim/complete/fail semantics.
Uses FOR UPDATE SKIP LOCKED for safe concurrent claiming.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infra.db_resilience_async import safe_db_conn
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


@dataclass
class Job:
    """A background job from the jobs table."""

    id: str
    tenant_id: str
    job_type: str
    payload: dict[str, Any]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    error_message: str | None
    scheduled_at: datetime
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


def _row_to_job(row) -> Job:
    """Convert an asyncpg Record to a Job dataclass."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Job(
        id=str(row["id"]),
        tenant_id=row["tenant_id"],
        job_type=row["job_type"],
        payload=payload,
        status=row["status"],
        priority=row["priority"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        error_message=row["error_message"],
        scheduled_at=row["scheduled_at"],
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


class AsyncPostgresJobRepository:
    """DB-backed job queue with claim/complete/fail semantics."""

    async def enqueue(
        self,
        tenant_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        priority: int = 0,
        max_attempts: int = 5,
        delay_seconds: float = 0,
    ) -> str:
        """
        Insert a new pending job.

        Args:
            tenant_id: Tenant identifier
            job_type: Job type string (e.g., 'outbound_reply', 'process_media')
            payload: JSON-serializable job data
            priority: Lower = higher priority (default 0, use -1 for high priority)
            max_attempts: Max retry attempts before marking as failed
            delay_seconds: Delay before first execution (0 = immediate)

        Returns:
            Job ID (UUID string)
        """
        async with safe_db_conn() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO jobs (tenant_id, job_type, payload, priority, max_attempts, scheduled_at)
                VALUES ($1, $2, $3::jsonb, $4, $5, now() + make_interval(secs => $6))
                RETURNING id
                """,
                tenant_id,
                job_type,
                json.dumps(payload),
                priority,
                max_attempts,
                float(delay_seconds),
            )
            job_id = str(row["id"])
            logger.debug(
                f"Job enqueued: id={job_id[:8]}, type={job_type}, priority={priority}",
                extra={"job_id": job_id, "job_type": job_type},
            )
            inc_counter("jobs_enqueued", job_type=job_type)
            return job_id

    async def claim_batch(self, batch_size: int = 5) -> list[Job]:
        """
        Atomically claim up to batch_size pending jobs that are due.

        Uses FOR UPDATE SKIP LOCKED for safe concurrent access
        (future-proof for multi-instance deployments).

        Returns:
            List of claimed Job objects (status changed to 'running')
        """
        async with safe_db_conn() as conn:
            rows = await conn.fetch(
                """
                WITH claimed AS (
                    SELECT id FROM jobs
                    WHERE status = 'pending'
                      AND scheduled_at <= now()
                    ORDER BY priority, created_at
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE jobs
                SET status = 'running', started_at = now()
                WHERE id IN (SELECT id FROM claimed)
                RETURNING *
                """,
                batch_size,
            )
            return [_row_to_job(row) for row in rows]

    async def complete(self, job_id: str) -> None:
        """Mark a job as completed."""
        async with safe_db_conn() as conn:
            await conn.execute(
                """
                UPDATE jobs
                SET status = 'completed', completed_at = now()
                WHERE id = $1
                """,
                job_id,
            )

    async def fail(
        self,
        job_id: str,
        error_message: str,
        *,
        base_delay: float = 5.0,
    ) -> None:
        """
        Record a job failure.

        If attempts < max_attempts, reschedule with exponential backoff.
        Otherwise mark as 'failed' permanently.

        Backoff formula: base_delay * 2^(attempts)
        With base_delay=5: 5s, 10s, 20s, 40s, 80s
        """
        async with safe_db_conn() as conn:
            await conn.execute(
                """
                UPDATE jobs
                SET
                  attempts = attempts + 1,
                  error_message = $2,
                  status = CASE
                    WHEN attempts + 1 < max_attempts THEN 'pending'
                    ELSE 'failed'
                  END,
                  scheduled_at = CASE
                    WHEN attempts + 1 < max_attempts
                      THEN now() + make_interval(secs => $3 * power(2, attempts))
                    ELSE scheduled_at
                  END,
                  completed_at = CASE
                    WHEN attempts + 1 >= max_attempts THEN now()
                    ELSE NULL
                  END
                WHERE id = $1
                """,
                job_id,
                error_message[:2000],  # Truncate long errors
                base_delay,
            )

    async def count_by_status(self, tenant_id: str | None = None) -> dict[str, int]:
        """Return {status: count} for admin visibility."""
        async with safe_db_conn() as conn:
            if tenant_id:
                rows = await conn.fetch(
                    "SELECT status, count(*)::int as cnt FROM jobs WHERE tenant_id = $1 GROUP BY status",
                    tenant_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT status, count(*)::int as cnt FROM jobs GROUP BY status",
                )
            return {row["status"]: row["cnt"] for row in rows}

    async def get_recent(
        self,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> list[Job]:
        """Get recent jobs for admin endpoint."""
        conditions = []
        params: list[Any] = []
        idx = 1

        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        if tenant_id:
            conditions.append(f"tenant_id = ${idx}")
            params.append(tenant_id)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        async with safe_db_conn() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ${idx}",
                *params,
            )
            return [_row_to_job(row) for row in rows]

    async def cleanup_completed(self, ttl_days: int = 7) -> int:
        """Delete completed jobs older than TTL. Returns count deleted."""
        async with safe_db_conn() as conn:
            result = await conn.execute(
                """
                DELETE FROM jobs
                WHERE status = 'completed'
                  AND completed_at < now() - make_interval(days => $1)
                """,
                ttl_days,
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info(f"Cleaned up {count} completed jobs older than {ttl_days} days")
            return count

    async def cleanup_failed(self, ttl_days: int = 30) -> int:
        """Delete failed jobs older than TTL. Returns count deleted."""
        async with safe_db_conn() as conn:
            result = await conn.execute(
                """
                DELETE FROM jobs
                WHERE status = 'failed'
                  AND completed_at < now() - make_interval(days => $1)
                """,
                ttl_days,
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info(f"Cleaned up {count} failed jobs older than {ttl_days} days")
            return count

    async def reset_stale_running(self, timeout_seconds: int = 300) -> int:
        """
        Safety net: reset jobs stuck in 'running' state longer than timeout.

        Handles process crashes where a job was claimed but never completed/failed.
        """
        async with safe_db_conn() as conn:
            result = await conn.execute(
                """
                UPDATE jobs
                SET status = 'pending', scheduled_at = now()
                WHERE status = 'running'
                  AND started_at < now() - make_interval(secs => $1)
                """,
                timeout_seconds,
            )
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.warning(f"Reset {count} stale running jobs (stuck > {timeout_seconds}s)")
                inc_counter("jobs_stale_reset")
            return count


# Global singleton
_job_repo: AsyncPostgresJobRepository | None = None


def get_job_repo() -> AsyncPostgresJobRepository:
    """Get the global job repository instance."""
    global _job_repo
    if _job_repo is None:
        _job_repo = AsyncPostgresJobRepository()
    return _job_repo
