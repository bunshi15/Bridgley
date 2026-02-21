# app/core/dispatch/jobs.py
"""
Dispatch job handlers — executed under WORKER_ROLE=dispatch (or all).

This module must NOT import bot handler modules.
"""
from __future__ import annotations

from app.infra.pg_job_repo_async import Job


async def handle_notify_crew_fallback(job: Job) -> None:
    """
    Send crew-safe copy-paste message to operator (Dispatch Layer Iteration 1).

    The operator receives a sanitized message they can forward to the
    crew WhatsApp group.  No PII is included — only locality, date,
    volume, floors, items summary, and estimate.

    Idempotency key pattern: ``lead_id + "crew_fallback_v1"``
    """
    from app.core.dispatch.services import notify_operator_crew_fallback

    payload = job.payload
    lead_id = payload["lead_id"]
    lead_payload = payload["payload"]

    success = await notify_operator_crew_fallback(
        lead_id, lead_payload,
        tenant_id=job.tenant_id,
    )
    if not success:
        raise RuntimeError(f"Crew fallback notification failed for lead {lead_id[:8]}")
