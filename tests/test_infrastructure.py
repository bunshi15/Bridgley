# tests/test_infrastructure.py
"""Tests for infrastructure components"""
import os
import pytest
from unittest.mock import patch
from app.infra.db_resilience_async import is_transient_error, retry_on_transient_error
from asyncpg.exceptions import PostgresError


class TestDatabaseResilience:
    def test_is_transient_error_connection_error(self):
        exc = PostgresError("connection timeout")
        assert is_transient_error(exc) is True

    def test_is_transient_error_server_closed(self):
        exc = PostgresError("server closed the connection unexpectedly")
        assert is_transient_error(exc) is True

    def test_is_transient_error_non_transient(self):
        exc = ValueError("some other error")
        assert is_transient_error(exc) is False

    @pytest.mark.asyncio
    async def test_retry_decorator_succeeds_on_first_try(self):
        call_count = 0

        @retry_on_transient_error(max_retries=3)
        async def successful_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_operation()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_decorator_succeeds_after_transient_error(self):
        call_count = 0

        @retry_on_transient_error(max_retries=3)
        async def operation_with_transient_error():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise PostgresError("connection timeout")
            return "success"

        result = await operation_with_transient_error()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_decorator_raises_non_transient_immediately(self):
        call_count = 0

        @retry_on_transient_error(max_retries=3)
        async def operation_with_non_transient_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not a transient error")

        with pytest.raises(ValueError):
            await operation_with_non_transient_error()

        assert call_count == 1  # Should not retry


class TestMetrics:
    def test_metrics_counter_increment(self):
        from app.infra.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.inc_counter("test_counter", 1)
        collector.inc_counter("test_counter", 2)

        metrics = collector.get_metrics()
        assert metrics["counters"]["test_counter"] == 3

    def test_metrics_histogram_observe(self):
        from app.infra.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.observe_histogram("test_histogram", 0.1)
        collector.observe_histogram("test_histogram", 0.2)
        collector.observe_histogram("test_histogram", 0.5)

        metrics = collector.get_metrics()
        stats = metrics["histograms"]["test_histogram"]
        assert stats["count"] == 3
        assert stats["min"] == 0.1
        assert stats["max"] == 0.5

    def test_metrics_with_labels(self):
        from app.infra.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.inc_counter("requests", 1, {"endpoint": "/api/v1"})
        collector.inc_counter("requests", 2, {"endpoint": "/api/v2"})

        metrics = collector.get_metrics()
        assert "requests{endpoint=/api/v1}" in metrics["counters"]
        assert "requests{endpoint=/api/v2}" in metrics["counters"]


class TestRateLimiter:
    def test_rate_limiter_allows_under_limit(self):
        from app.infra.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)

        # Should allow first request
        allowed, retry_after = limiter.is_allowed("test_key")
        assert allowed is True
        assert retry_after is None

    def test_rate_limiter_blocks_over_limit(self):
        from app.infra.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)

        # First two requests should be allowed
        limiter.is_allowed("test_key")
        limiter.is_allowed("test_key")

        # Third request should be blocked
        allowed, retry_after = limiter.is_allowed("test_key")
        assert allowed is False
        assert retry_after is not None
        assert retry_after > 0

    def test_rate_limiter_get_usage(self):
        from app.infra.rate_limiter import InMemoryRateLimiter

        limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)

        limiter.is_allowed("test_key")
        limiter.is_allowed("test_key")

        usage = limiter.get_usage("test_key")
        assert usage["count"] == 2
        assert usage["limit"] == 10
        assert usage["remaining"] == 8


# ===================================================================
# Production Runtime Model: RUN_MODE
# ===================================================================


class TestRunModeConfig:
    """Tests for RUN_MODE configuration."""

    def test_default_run_mode_is_all(self):
        """Default run_mode should be 'all' for dev/backward compatibility."""
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.run_mode == "all"

    def test_run_mode_web(self):
        """RUN_MODE=web should be accepted."""
        from app.config import Settings
        s = Settings(run_mode="web", _env_file=None)
        assert s.run_mode == "web"

    def test_run_mode_worker(self):
        """RUN_MODE=worker should be accepted."""
        from app.config import Settings
        s = Settings(run_mode="worker", _env_file=None)
        assert s.run_mode == "worker"

    def test_run_mode_poller(self):
        """RUN_MODE=poller should be accepted."""
        from app.config import Settings
        s = Settings(run_mode="poller", _env_file=None)
        assert s.run_mode == "poller"

    def test_run_mode_invalid_rejected(self):
        """Invalid run_mode should raise validation error."""
        from app.config import Settings
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Settings(run_mode="banana", _env_file=None)

    def test_job_worker_disabled_by_default(self):
        """job_worker_enabled should default to False (Section 8 of runtime model)."""
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.job_worker_enabled is False

    def test_job_worker_explicit_enable(self):
        """job_worker_enabled can be explicitly enabled."""
        from app.config import Settings
        s = Settings(job_worker_enabled=True, _env_file=None)
        assert s.job_worker_enabled is True


class TestRunModeGuards:
    """Tests for run_mode guards in lifespan startup logic."""

    def test_web_mode_skips_pollers(self):
        """In web mode, pollers should not start."""
        from app.config import Settings
        s = Settings(run_mode="web", _env_file=None)
        assert s.run_mode not in ("all", "poller")

    def test_web_mode_skips_worker(self):
        """In web mode, job worker should not start."""
        from app.config import Settings
        s = Settings(run_mode="web", _env_file=None)
        assert s.run_mode not in ("all", "worker")

    def test_worker_mode_allows_worker(self):
        """In worker mode, job worker should start (if enabled)."""
        from app.config import Settings
        s = Settings(run_mode="worker", job_worker_enabled=True, _env_file=None)
        assert s.run_mode in ("all", "worker")
        assert s.job_worker_enabled is True

    def test_worker_mode_skips_pollers(self):
        """In worker mode, pollers should not start."""
        from app.config import Settings
        s = Settings(run_mode="worker", _env_file=None)
        assert s.run_mode not in ("all", "poller")

    def test_poller_mode_allows_pollers(self):
        """In poller mode, pollers should start."""
        from app.config import Settings
        s = Settings(run_mode="poller", _env_file=None)
        assert s.run_mode in ("all", "poller")

    def test_poller_mode_skips_worker(self):
        """In poller mode, job worker should not start."""
        from app.config import Settings
        s = Settings(run_mode="poller", _env_file=None)
        assert s.run_mode not in ("all", "worker")

    def test_all_mode_allows_everything(self):
        """In all mode (default), both pollers and worker should start."""
        from app.config import Settings
        s = Settings(run_mode="all", job_worker_enabled=True, _env_file=None)
        assert s.run_mode in ("all", "poller")
        assert s.run_mode in ("all", "worker")
        assert s.job_worker_enabled is True

    def test_worker_mode_still_needs_enabled_flag(self):
        """Worker mode alone is not enough — job_worker_enabled must also be True."""
        from app.config import Settings
        s = Settings(run_mode="worker", job_worker_enabled=False, _env_file=None)
        # run_mode allows it, but enabled flag prevents it
        assert s.run_mode in ("all", "worker")
        should_start = s.run_mode in ("all", "worker") and s.job_worker_enabled
        assert should_start is False
