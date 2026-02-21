# tests/test_job_queue.py
"""
Tests for the v0.7 DB-backed job queue:
- Job dataclass
- Job repository (pg_job_repo_async.py)
- Job worker dispatch logic (job_worker.py)
- Job handler functions
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infra.pg_job_repo_async import Job, AsyncPostgresJobRepository, _row_to_job
from app.infra.job_worker import (
    JobWorker,
    handle_outbound_reply,
    handle_process_media,
    handle_notify_operator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(
    *,
    job_type: str = "outbound_reply",
    payload: dict | None = None,
    status: str = "running",
    attempts: int = 0,
    max_attempts: int = 5,
) -> Job:
    """Create a test Job instance."""
    return Job(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        tenant_id="test_tenant",
        job_type=job_type,
        payload=payload or {},
        status=status,
        priority=0,
        attempts=attempts,
        max_attempts=max_attempts,
        error_message=None,
        scheduled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        completed_at=None,
    )


def _make_row(overrides: dict | None = None) -> dict:
    """Create a dict that mimics an asyncpg Record for _row_to_job."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "tenant_id": "test_tenant",
        "job_type": "outbound_reply",
        "payload": '{"provider": "telegram", "chat_id": "123", "text": "hi"}',
        "status": "pending",
        "priority": 0,
        "attempts": 0,
        "max_attempts": 5,
        "error_message": None,
        "scheduled_at": now,
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    if overrides:
        row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Job Dataclass
# ---------------------------------------------------------------------------

class TestJobDataclass:
    def test_job_construction(self):
        job = _make_job()
        assert job.id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert job.tenant_id == "test_tenant"
        assert job.job_type == "outbound_reply"
        assert job.status == "running"

    def test_row_to_job_parses_json_string(self):
        row = _make_row()
        job = _row_to_job(row)
        assert job.payload == {"provider": "telegram", "chat_id": "123", "text": "hi"}
        assert job.status == "pending"

    def test_row_to_job_handles_dict_payload(self):
        """When asyncpg auto-parses JSONB, payload is already a dict."""
        row = _make_row({"payload": {"key": "value"}})
        job = _row_to_job(row)
        assert job.payload == {"key": "value"}


# ---------------------------------------------------------------------------
# Job Repository
# ---------------------------------------------------------------------------

class TestJobRepository:
    @pytest.mark.asyncio
    async def test_enqueue_returns_uuid(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": "some-uuid-1234"})

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await repo.enqueue(
                tenant_id="t1",
                job_type="outbound_reply",
                payload={"provider": "telegram", "chat_id": "123", "text": "hello"},
                priority=-1,
                max_attempts=5,
            )

        assert result == "some-uuid-1234"
        mock_conn.fetchrow.assert_called_once()
        # Verify SQL contains INSERT INTO jobs
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO jobs" in sql_arg
        # Verify payload was serialized to JSON
        payload_arg = mock_conn.fetchrow.call_args[0][3]
        parsed = json.loads(payload_arg)
        assert parsed["provider"] == "telegram"

    @pytest.mark.asyncio
    async def test_claim_batch_returns_jobs(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        rows = [_make_row({"status": "running"})]
        mock_conn.fetch = AsyncMock(return_value=rows)

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            jobs = await repo.claim_batch(batch_size=5)

        assert len(jobs) == 1
        assert jobs[0].status == "running"
        # Verify SQL uses FOR UPDATE SKIP LOCKED
        sql_arg = mock_conn.fetch.call_args[0][0]
        assert "FOR UPDATE SKIP LOCKED" in sql_arg

    @pytest.mark.asyncio
    async def test_claim_batch_empty(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            jobs = await repo.claim_batch(batch_size=5)

        assert jobs == []

    @pytest.mark.asyncio
    async def test_complete_updates_status(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await repo.complete("job-id-123")

        mock_conn.execute.assert_called_once()
        sql_arg = mock_conn.execute.call_args[0][0]
        assert "completed" in sql_arg
        assert mock_conn.execute.call_args[0][1] == "job-id-123"

    @pytest.mark.asyncio
    async def test_fail_with_retry(self):
        """When attempts < max_attempts, job should be rescheduled."""
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await repo.fail("job-id-123", "Connection timeout", base_delay=5.0)

        mock_conn.execute.assert_called_once()
        sql_arg = mock_conn.execute.call_args[0][0]
        # SQL should contain CASE logic for retry vs permanent fail
        assert "CASE" in sql_arg
        assert "pending" in sql_arg
        assert "failed" in sql_arg
        # Error message should be passed
        assert mock_conn.execute.call_args[0][2] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_cleanup_completed(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 5")

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await repo.cleanup_completed(ttl_days=7)

        assert count == 5

    @pytest.mark.asyncio
    async def test_reset_stale_running(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 2")

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await repo.reset_stale_running(timeout_seconds=300)

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_by_status(self):
        repo = AsyncPostgresJobRepository()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"status": "pending", "cnt": 3},
            {"status": "completed", "cnt": 10},
        ])

        with patch("app.infra.pg_job_repo_async.safe_db_conn") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            counts = await repo.count_by_status()

        assert counts == {"pending": 3, "completed": 10}


# ---------------------------------------------------------------------------
# Job Worker
# ---------------------------------------------------------------------------

class TestJobWorker:
    @pytest.mark.asyncio
    async def test_worker_dispatches_to_handler(self):
        """Worker calls the right handler and marks the job complete."""
        mock_repo = AsyncMock(spec=AsyncPostgresJobRepository)
        job = _make_job(
            job_type="outbound_reply",
            payload={"provider": "telegram", "chat_id": "123", "text": "hi"},
        )

        mock_handler = AsyncMock()
        worker = JobWorker(repo=mock_repo)
        worker.register("outbound_reply", mock_handler)

        await worker._execute(job)

        mock_handler.assert_called_once_with(job)
        mock_repo.complete.assert_called_once_with(job.id)

    @pytest.mark.asyncio
    async def test_worker_fails_job_on_handler_error(self):
        """When handler raises, worker calls repo.fail()."""
        mock_repo = AsyncMock(spec=AsyncPostgresJobRepository)
        job = _make_job(job_type="outbound_reply")

        mock_handler = AsyncMock(side_effect=RuntimeError("Network error"))
        worker = JobWorker(repo=mock_repo, base_retry_delay=5.0)
        worker.register("outbound_reply", mock_handler)

        await worker._execute(job)

        mock_repo.fail.assert_called_once()
        fail_args = mock_repo.fail.call_args
        assert fail_args[0][0] == job.id
        assert "RuntimeError" in fail_args[0][1]
        mock_repo.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_unknown_job_type(self):
        """Unknown job_type fails the job with descriptive error."""
        mock_repo = AsyncMock(spec=AsyncPostgresJobRepository)
        job = _make_job(job_type="unknown_type")

        worker = JobWorker(repo=mock_repo)

        await worker._execute(job)

        mock_repo.fail.assert_called_once()
        error_msg = mock_repo.fail.call_args[0][1]
        assert "No handler registered" in error_msg
        assert "unknown_type" in error_msg

    @pytest.mark.asyncio
    async def test_worker_start_stop(self):
        """Worker starts and stops cleanly."""
        mock_repo = AsyncMock(spec=AsyncPostgresJobRepository)
        mock_repo.claim_batch = AsyncMock(return_value=[])
        mock_repo.reset_stale_running = AsyncMock(return_value=0)

        worker = JobWorker(repo=mock_repo, poll_interval=0.05)
        await worker.start()

        assert worker._running is True
        assert worker._task is not None

        # Let it run one poll cycle
        await asyncio.sleep(0.1)

        await worker.stop()
        assert worker._running is False


# ---------------------------------------------------------------------------
# Job Handlers
# ---------------------------------------------------------------------------

class TestJobHandlers:
    @pytest.mark.asyncio
    async def test_handle_outbound_reply_telegram(self):
        """Calls telegram_sender.send_text_message with correct args."""
        job = _make_job(
            job_type="outbound_reply",
            payload={
                "provider": "telegram",
                "chat_id": "12345",
                "text": "Hello there!",
                "message_id": "msg_1",
            },
        )

        with patch("app.infra.job_worker.inc_counter"):
            with patch(
                "app.transport.telegram_sender.send_text_message",
                new_callable=AsyncMock,
            ) as mock_send:
                await handle_outbound_reply(job)

        mock_send.assert_called_once_with("12345", "Hello there!", token=None)

    @pytest.mark.asyncio
    async def test_handle_outbound_reply_meta(self):
        """Calls meta_sender.send_text_message with correct args."""
        job = _make_job(
            job_type="outbound_reply",
            payload={
                "provider": "meta",
                "chat_id": "972501234567",
                "text": "Reply text",
                "message_id": "msg_2",
            },
        )

        with patch("app.infra.job_worker.inc_counter"):
            with patch(
                "app.transport.meta_sender.send_text_message",
                new_callable=AsyncMock,
            ) as mock_send:
                await handle_outbound_reply(job)

        mock_send.assert_called_once_with(
            "972501234567", "Reply text",
            access_token=None, phone_number_id=None,
        )

    @pytest.mark.asyncio
    async def test_handle_outbound_reply_unknown_provider(self):
        """Raises ValueError for unknown provider."""
        job = _make_job(
            job_type="outbound_reply",
            payload={"provider": "sms", "chat_id": "1", "text": "x"},
        )

        with patch("app.infra.job_worker.inc_counter"):
            with pytest.raises(ValueError, match="Unknown provider"):
                await handle_outbound_reply(job)

    @pytest.mark.asyncio
    async def test_handle_process_media(self):
        """Calls media_service.process_and_save for each media item."""
        job = _make_job(
            job_type="process_media",
            payload={
                "provider": "telegram",
                "tenant_id": "t1",
                "chat_id": "123",
                "message_id": "msg_3",
                "media_items": [
                    {
                        "url": "",
                        "content_type": "image/jpeg",
                        "size_bytes": 1024,
                        "provider_media_id": "file_abc",
                    }
                ],
            },
        )

        mock_service = MagicMock()
        mock_service.process_and_save = AsyncMock(
            return_value={"uuid": "photo-uuid", "size_bytes": 512}
        )

        # Patch where the function is actually imported (local import in handler)
        with patch("app.infra.media_service.get_media_service", return_value=mock_service):
            await handle_process_media(job)

        mock_service.process_and_save.assert_called_once()
        call_args = mock_service.process_and_save.call_args
        # First positional arg is the MediaItem
        media_item = call_args[0][0]
        assert media_item.provider_media_id == "file_abc"

    @pytest.mark.asyncio
    async def test_handle_notify_operator_success(self):
        """Calls notify_operator and succeeds."""
        job = _make_job(
            job_type="notify_operator",
            payload={
                "lead_id": "lead_abc",
                "chat_id": "123",
                "payload": {"cargo_description": "boxes"},
            },
        )

        with patch(
            "app.infra.notification_service.notify_operator",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify:
            await handle_notify_operator(job)

        mock_notify.assert_called_once_with(
            "lead_abc", "123", {"cargo_description": "boxes"},
            tenant_id="test_tenant",
        )

    @pytest.mark.asyncio
    async def test_handle_notify_operator_failure_raises(self):
        """Raises RuntimeError when notify_operator returns False (triggers retry)."""
        job = _make_job(
            job_type="notify_operator",
            payload={
                "lead_id": "lead_abc",
                "chat_id": "123",
                "payload": {},
            },
        )

        with patch(
            "app.infra.notification_service.notify_operator",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(RuntimeError, match="Operator notification failed"):
                await handle_notify_operator(job)


# ---------------------------------------------------------------------------
# Telegram Poller (v0.8.1)
# ---------------------------------------------------------------------------

class TestTelegramPollerTenantAware:
    """Test TelegramPoller with tenant context."""

    def test_poller_created_with_tenant_ctx(self):
        """Constructor stores tenant context and extracts bot_token."""
        from app.transport.telegram_polling import TelegramPoller
        from app.infra.tenant_registry import TenantContext, ChannelBinding

        ctx = TenantContext(
            tenant_id="t_poller",
            display_name="Poller Tenant",
            is_active=True,
            config={},
            channels={
                "telegram": ChannelBinding(
                    provider="telegram",
                    credentials={"bot_token": "123:ABC"},
                    config={"channel_mode": "polling"},
                ),
            },
        )
        engine = MagicMock()
        poller = TelegramPoller(engine=engine, tenant_ctx=ctx)

        assert poller._tenant_ctx is ctx
        assert poller._bot_token == "123:ABC"
        assert poller._tenant_id == "t_poller"

    def test_poller_without_tenant_ctx_uses_defaults(self):
        """Without tenant_ctx, bot_token is None (uses settings.*)."""
        from app.transport.telegram_polling import TelegramPoller

        engine = MagicMock()
        poller = TelegramPoller(engine=engine)

        assert poller._tenant_ctx is None
        assert poller._bot_token is None

    def test_poller_tenant_without_telegram_channel(self):
        """Tenant without telegram in channels → bot_token is None."""
        from app.transport.telegram_polling import TelegramPoller
        from app.infra.tenant_registry import TenantContext

        ctx = TenantContext(
            tenant_id="t_meta_only",
            display_name="Meta Only",
            is_active=True,
            config={},
            channels={},  # No telegram channel
        )
        engine = MagicMock()
        poller = TelegramPoller(engine=engine, tenant_ctx=ctx)

        assert poller._bot_token is None

    @pytest.mark.asyncio
    async def test_poller_passes_token_to_get_updates(self):
        """_poll_loop passes the tenant's bot_token to get_updates."""
        from app.transport.telegram_polling import TelegramPoller
        from app.infra.tenant_registry import TenantContext, ChannelBinding

        ctx = TenantContext(
            tenant_id="t_poll",
            display_name="Poll",
            is_active=True,
            config={},
            channels={
                "telegram": ChannelBinding(
                    provider="telegram",
                    credentials={"bot_token": "999:XYZ"},
                    config={"channel_mode": "polling"},
                ),
            },
        )
        engine = MagicMock()
        poller = TelegramPoller(engine=engine, poll_timeout=1, tenant_ctx=ctx)

        # Make get_updates raise CancelledError after first call to break the loop
        call_count = 0

        async def _mock_get_updates(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            return []

        with patch(
            "app.transport.telegram_polling.get_updates",
            side_effect=_mock_get_updates,
        ) as mock_gu:
            with patch(
                "app.transport.telegram_polling.delete_webhook",
                new_callable=AsyncMock,
            ):
                await poller.start()
                # Wait for the task to finish (it exits via CancelledError)
                try:
                    await asyncio.wait_for(poller._task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                poller._running = False

        # Verify get_updates was called with the tenant's token
        assert call_count >= 1
        first_call_kwargs = mock_gu.call_args_list[0][1]
        assert first_call_kwargs.get("token") == "999:XYZ"


# ---------------------------------------------------------------------------
# _start_telegram_pollers helper (v0.8.1)
# ---------------------------------------------------------------------------

class TestStartTelegramPollers:
    """Test _start_telegram_pollers helper function."""

    @pytest.mark.asyncio
    async def test_starts_poller_for_polling_tenant(self, monkeypatch):
        """Creates a poller for tenants with channel_mode=polling."""
        from app.transport.http_app import _start_telegram_pollers
        from app.infra.tenant_registry import TenantContext, ChannelBinding, reset_cache
        import app.infra.tenant_registry as reg

        reg._cache = {
            "t_poll": TenantContext(
                "t_poll", "Polling Tenant", True, {},
                channels={
                    "telegram": ChannelBinding(
                        "telegram",
                        {"bot_token": "111:AAA"},
                        {"channel_mode": "polling"},
                    ),
                },
            ),
        }

        engine = MagicMock()

        with patch(
            "app.transport.telegram_polling.TelegramPoller.start",
            new_callable=AsyncMock,
        ) as mock_start:
            pollers = await _start_telegram_pollers(engine)

        assert "t_poll" in pollers
        mock_start.assert_called_once()
        reset_cache()

    @pytest.mark.asyncio
    async def test_skips_webhook_mode_tenant(self, monkeypatch):
        """Does NOT create poller for channel_mode=webhook tenants."""
        from app.transport.http_app import _start_telegram_pollers
        from app.infra.tenant_registry import TenantContext, ChannelBinding, reset_cache
        import app.infra.tenant_registry as reg

        reg._cache = {
            "t_wh": TenantContext(
                "t_wh", "Webhook Tenant", True, {},
                channels={
                    "telegram": ChannelBinding(
                        "telegram",
                        {"bot_token": "222:BBB"},
                        {"channel_mode": "webhook"},
                    ),
                },
            ),
        }

        engine = MagicMock()

        # Also prevent legacy fallback
        monkeypatch.setattr("app.config.settings.channel_provider", "meta")

        pollers = await _start_telegram_pollers(engine)

        assert len(pollers) == 0
        reset_cache()

    @pytest.mark.asyncio
    async def test_legacy_fallback_single_tenant(self, monkeypatch):
        """Falls back to legacy single-tenant mode if no DB tenants use polling."""
        from app.transport.http_app import _start_telegram_pollers
        from app.infra.tenant_registry import reset_cache
        import app.infra.tenant_registry as reg

        reg._cache = {}  # No tenants in registry

        monkeypatch.setattr("app.config.settings.channel_provider", "telegram")
        monkeypatch.setattr("app.config.settings.telegram_channel_mode", "polling")

        engine = MagicMock()

        with patch(
            "app.transport.telegram_polling.TelegramPoller.start",
            new_callable=AsyncMock,
        ):
            pollers = await _start_telegram_pollers(engine)

        assert "__default__" in pollers
        assert len(pollers) == 1
        reset_cache()

    @pytest.mark.asyncio
    async def test_no_pollers_when_no_telegram(self, monkeypatch):
        """No pollers started when no tenants and no legacy telegram config."""
        from app.transport.http_app import _start_telegram_pollers
        from app.infra.tenant_registry import reset_cache
        import app.infra.tenant_registry as reg

        reg._cache = {}

        monkeypatch.setattr("app.config.settings.channel_provider", "meta")

        engine = MagicMock()
        pollers = await _start_telegram_pollers(engine)

        assert len(pollers) == 0
        reset_cache()
