# app/infra/job_worker.py
"""
In-process async job worker with handler dispatch.

Polls the jobs table, claims pending jobs, and routes them
to registered handler functions. Supports concurrent batch
execution with automatic retry on failure.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter
from app.infra.pg_job_repo_async import AsyncPostgresJobRepository, Job

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job handler functions
# ---------------------------------------------------------------------------

async def handle_outbound_reply(job: Job) -> None:
    """Send a text reply to customer via the appropriate provider API."""
    from app.infra.tenant_registry import get_tenant_for_channel

    payload = job.payload
    provider = payload["provider"]
    chat_id = payload["chat_id"]
    text = payload["text"]

    # Look up tenant credentials (None = use settings.* fallback)
    binding = get_tenant_for_channel(job.tenant_id, provider)

    if provider == "telegram":
        from app.transport.telegram_sender import send_text_message
        token = binding.credentials.get("bot_token") if binding else None
        await send_text_message(chat_id, text, token=token)

    elif provider == "meta":
        from app.transport.meta_sender import send_text_message
        access_token = binding.credentials.get("access_token") if binding else None
        phone_number_id = binding.config.get("phone_number_id") if binding else None
        await send_text_message(
            chat_id, text,
            access_token=access_token,
            phone_number_id=phone_number_id,
        )

    else:
        raise ValueError(f"Unknown provider for outbound_reply: {provider}")

    inc_counter("outbound_messages_total", provider=provider, status="sent")
    logger.info(
        f"Outbound reply sent: provider={provider}, chat={chat_id[:6]}***",
        extra={"provider": provider, "job_id": job.id},
    )


async def handle_process_media(job: Job) -> None:
    """Download, validate, re-encode, and save media attachments."""
    from app.core.engine.domain import MediaItem
    from app.infra.media_service import get_media_service
    from app.infra.tenant_registry import get_tenant_for_channel

    payload = job.payload
    provider = payload["provider"]
    tenant_id = payload["tenant_id"]
    chat_id = payload["chat_id"]
    message_id = payload.get("message_id", "")

    # Look up tenant credentials for media URL resolution
    binding = get_tenant_for_channel(job.tenant_id, provider)

    media_service = get_media_service()

    for item_data in payload.get("media_items", []):
        media_item = MediaItem(
            url=item_data.get("url", ""),
            content_type=item_data.get("content_type"),
            size_bytes=item_data.get("size_bytes"),
            provider_media_id=item_data.get("provider_media_id"),
        )

        # For Meta HTTP strategy: resolve media ID to URL
        if provider == "meta" and not media_item.url and media_item.provider_media_id:
            from app.config import settings
            if settings.meta_media_fetch_strategy != "provider_api":
                from app.transport.meta_sender import get_media_url
                access_token = binding.credentials.get("access_token") if binding else None
                download_url = await get_media_url(
                    media_item.provider_media_id,
                    access_token=access_token,
                )
                if not download_url:
                    raise RuntimeError(
                        f"Could not resolve Meta media ID: "
                        f"{media_item.provider_media_id[:20]}"
                    )
                media_item.url = download_url

        processed = await media_service.process_and_save(
            media_item,
            tenant_id,
            chat_id,
            provider=provider,
            message_id=message_id,
        )
        if processed:
            logger.info(
                f"Job media processed: photo_id={processed.get('uuid', 'n/a')[:8]}",
                extra={"job_id": job.id, "provider": provider},
            )


async def handle_notify_operator(job: Job) -> None:
    """Send lead notification to operator via configured channel."""
    from app.infra.notification_service import notify_operator

    payload = job.payload
    lead_id = payload["lead_id"]
    chat_id = payload["chat_id"]
    lead_payload = payload["payload"]

    success = await notify_operator(
        lead_id, chat_id, lead_payload,
        tenant_id=job.tenant_id,
    )
    if not success:
        raise RuntimeError(f"Operator notification failed for lead {lead_id[:8]}")


async def handle_notify_crew_fallback(job: Job) -> None:
    """
    Send crew-safe copy-paste message to operator (Dispatch Layer Iteration 1).

    The operator receives a sanitized message they can forward to the
    crew WhatsApp group.  No PII is included — only locality, date,
    volume, floors, items summary, and estimate.

    Idempotency key pattern: ``lead_id + "crew_fallback_v1"``
    """
    from app.infra.notification_service import format_crew_message, notify_operator_crew_fallback

    payload = job.payload
    lead_id = payload["lead_id"]
    lead_payload = payload["payload"]

    success = await notify_operator_crew_fallback(
        lead_id, lead_payload,
        tenant_id=job.tenant_id,
    )
    if not success:
        raise RuntimeError(f"Crew fallback notification failed for lead {lead_id[:8]}")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class JobWorker:
    """
    In-process async worker that polls the jobs table and executes handlers.

    Usage:
        worker = JobWorker(repo=get_job_repo())
        worker.register("outbound_reply", handle_outbound_reply)
        await worker.start()
        ...
        await worker.stop()
    """

    def __init__(
        self,
        repo: AsyncPostgresJobRepository,
        *,
        poll_interval: float = 1.0,
        batch_size: int = 5,
        base_retry_delay: float = 5.0,
        stale_timeout: int = 300,
    ):
        self._repo = repo
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._base_retry_delay = base_retry_delay
        self._stale_timeout = stale_timeout
        self._handlers: dict[str, Callable[[Job], Awaitable[None]]] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._loop_count = 0

    def register(self, job_type: str, handler: Callable[[Job], Awaitable[None]]) -> None:
        """Register a handler function for a job type."""
        self._handlers[job_type] = handler

    async def start(self) -> None:
        """Start the worker loop as an asyncio task."""
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="job_worker")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            f"Job worker started: poll={self._poll_interval}s, "
            f"batch={self._batch_size}, handlers={list(self._handlers.keys())}",
        )

    async def stop(self) -> None:
        """Graceful shutdown: stop polling and wait for current batch to finish."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Job worker stopped")

    async def _loop(self) -> None:
        """Main poll loop."""
        while self._running:
            try:
                self._loop_count += 1

                # Periodically reset stale running jobs (~every 60 loops)
                if self._loop_count % 60 == 0:
                    try:
                        await self._repo.reset_stale_running(self._stale_timeout)
                    except Exception as exc:
                        logger.warning(f"Stale job reset failed: {exc}")

                jobs = await self._repo.claim_batch(self._batch_size)

                if jobs:
                    # Process claimed jobs concurrently within batch
                    tasks = [self._execute(job) for job in jobs]
                    await asyncio.gather(*tasks, return_exceptions=True)
                    # Small delay between batches when there's work
                    await asyncio.sleep(0.1)
                else:
                    # No work: back off to poll interval
                    await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Job worker loop error: {exc}", exc_info=True)
                inc_counter("job_worker_loop_errors")
                await asyncio.sleep(self._poll_interval * 2)

    async def _execute(self, job: Job) -> None:
        """Execute a single job via its registered handler."""
        handler = self._handlers.get(job.job_type)
        if handler is None:
            error = f"No handler registered for job_type={job.job_type}"
            logger.error(error)
            await self._repo.fail(job.id, error, base_delay=self._base_retry_delay)
            inc_counter("jobs_unknown_type")
            return

        try:
            await handler(job)
            await self._repo.complete(job.id)
            inc_counter("jobs_completed", job_type=job.job_type)
            logger.info(
                f"Job completed: id={job.id[:8]}, type={job.job_type}, "
                f"attempt={job.attempts + 1}",
            )
        except Exception as exc:
            error_msg = f"{exc.__class__.__name__}: {exc}"[:500]
            await self._repo.fail(
                job.id, error_msg, base_delay=self._base_retry_delay,
            )
            inc_counter("jobs_failed_attempt", job_type=job.job_type)
            logger.warning(
                f"Job failed: id={job.id[:8]}, type={job.job_type}, "
                f"attempt={job.attempts + 1}, error={error_msg[:100]}",
            )

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """Log unexpected worker death."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(
                f"Job worker task died unexpectedly: {exc}",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
