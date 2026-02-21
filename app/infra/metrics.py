# app/infra/metrics.py
from __future__ import annotations
import time
from collections import defaultdict
from threading import Lock
from typing import Dict, Any
from dataclasses import dataclass, field
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Counter:
    """Simple counter metric"""
    value: int = 0

    def inc(self, amount: int = 1) -> None:
        self.value += amount


@dataclass
class Histogram:
    """Track distribution of values (e.g., response times)"""
    values: list[float] = field(default_factory=list)

    def observe(self, value: float) -> None:
        self.values.append(value)

    def get_stats(self) -> dict:
        if not self.values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p95": 0, "p99": 0}

        sorted_values = sorted(self.values)
        count = len(sorted_values)

        def percentile(p: float) -> float:
            idx = int(count * p)
            return sorted_values[min(idx, count - 1)]

        return {
            "count": count,
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "avg": sum(sorted_values) / count,
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        }


class MetricsCollector:
    """
    Lightweight metrics collection.
    For production, consider Prometheus client or similar.
    """

    def __init__(self):
        self._counters: Dict[str, Counter] = defaultdict(Counter)
        self._histograms: Dict[str, Histogram] = defaultdict(Histogram)
        self._lock = Lock()

    def inc_counter(self, name: str, amount: int = 1, labels: dict | None = None) -> None:
        """Increment a counter metric"""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key].inc(amount)

    def observe_histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        """Add a value to histogram"""
        key = self._make_key(name, labels)
        with self._lock:
            self._histograms[key].observe(value)

    def get_metrics(self) -> dict:
        """Get all current metrics"""
        with self._lock:
            counters = {k: v.value for k, v in self._counters.items()}
            histograms = {k: v.get_stats() for k, v in self._histograms.items()}

        return {
            "counters": counters,
            "histograms": histograms,
        }

    def reset(self) -> None:
        """Reset all metrics"""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
        logger.info("Metrics reset")

    @staticmethod
    def _make_key(name: str, labels: dict | None) -> str:
        """Create a metric key from name and labels"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Global metrics collector
_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector"""
    return _metrics


# Convenience functions
def inc_counter(name: str, amount: int = 1, **labels) -> None:
    """Increment a counter metric"""
    _metrics.inc_counter(name, amount, labels or None)


def observe_histogram(name: str, value: float, **labels) -> None:
    """Record a histogram value"""
    _metrics.observe_histogram(name, value, labels or None)


# Context manager for timing operations
class Timer:
    """Context manager to time operations"""

    def __init__(self, metric_name: str, **labels):
        self.metric_name = metric_name
        self.labels = labels
        self.start_time: float | None = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            observe_histogram(self.metric_name, duration, **self.labels)


# Application-specific metrics
class AppMetrics:
    """Application-level metrics tracking"""

    @staticmethod
    def request_received(tenant_id: str, step: str) -> None:
        inc_counter("bot_requests_total", tenant_id=tenant_id, step=step)

    @staticmethod
    def lead_created(tenant_id: str) -> None:
        inc_counter("leads_created_total", tenant_id=tenant_id)

    @staticmethod
    def session_created(tenant_id: str) -> None:
        inc_counter("sessions_created_total", tenant_id=tenant_id)

    @staticmethod
    def session_expired(tenant_id: str) -> None:
        inc_counter("sessions_expired_total", tenant_id=tenant_id)

    @staticmethod
    def idempotency_hit(tenant_id: str, provider: str) -> None:
        inc_counter("idempotency_hits_total", tenant_id=tenant_id, provider=provider)

    @staticmethod
    def database_error(operation: str) -> None:
        inc_counter("database_errors_total", operation=operation)

    @staticmethod
    def webhook_validation_failed(provider: str) -> None:
        inc_counter("webhook_validation_failures_total", provider=provider)

    @staticmethod
    def track_processing_time(tenant_id: str, step: str) -> Timer:
        return Timer("request_processing_seconds", tenant_id=tenant_id, step=step)