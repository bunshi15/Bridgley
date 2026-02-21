# app/infra/audit_log.py
"""
Audit logging for sensitive administrative operations.

Records tenant management actions to a dedicated audit logger
(separate from the application log) with structured context.

Events are logged at INFO level to a logger named "audit" so they
can be routed to a separate file / sink via logging configuration.

Future: persist audit events to a DB table for queryability.
"""
from __future__ import annotations

import logging
from typing import Any

# Dedicated audit logger — separate from the app logger.
# Can be configured independently (e.g., to a separate file/sink).
_audit_logger = logging.getLogger("audit")


def audit_event(
    action: str,
    *,
    tenant_id: str | None = None,
    provider: str | None = None,
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Record an audit event.

    Args:
        action: Action name (e.g., "tenant.create", "channel.upsert")
        tenant_id: Tenant affected (if applicable)
        provider: Channel provider affected (if applicable)
        detail: Human-readable detail
        extra: Additional structured context
    """
    record = {
        "audit_action": action,
        "tenant_id": tenant_id or "",
        "provider": provider or "",
        "detail": detail,
    }
    if extra:
        record.update(extra)

    _audit_logger.info(
        f"AUDIT: {action} tenant={tenant_id or '-'} provider={provider or '-'} {detail}",
        extra=record,
    )
