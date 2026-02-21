# app/core/dispatch/services.py
"""
Dispatch notification services — isolated from bot engines.

This module must NOT import bot handler modules.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.infra.metrics import inc_counter

logger = logging.getLogger(__name__)


async def notify_operator_crew_fallback(
    lead_id: str,
    payload: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> bool:
    """
    Send crew-safe fallback message to operator (Dispatch Layer Iteration 1).

    The operator receives a sanitized, copy-paste ready message that they can
    forward to the crew WhatsApp group. **No PII** is included.

    This is sent as a separate message after the full lead notification,
    using the same notification channel.

    Args:
        lead_id: The lead identifier
        payload: The lead data
        tenant_id: Tenant to resolve operator config for (None = global)

    Returns:
        True if notification was sent/queued successfully, False otherwise
    """
    from app.infra.notification_channels import (
        OperatorNotification,
        get_notification_channel,
    )
    from app.infra.tenant_registry import get_operator_config
    from app.core.dispatch.crew_view import format_crew_message

    op_cfg = get_operator_config(tenant_id)

    if not op_cfg["enabled"]:
        logger.debug(
            "Operator notifications disabled for tenant=%s, skipping crew fallback",
            tenant_id or "global",
        )
        return True

    resolved_tenant_id = tenant_id or settings.tenant_id

    try:
        crew_body = format_crew_message(lead_id, payload)

        notification = OperatorNotification(
            lead_id=lead_id,
            chat_id="",  # No customer chat_id in crew message (PII-safe)
            body=crew_body,
            photo_urls=[],  # No photos in crew message
            metadata={},
        )

        channel = get_notification_channel(tenant_id=tenant_id)
        logger.info(
            "Sending crew fallback via %s: lead_id=%s, tenant=%s",
            channel.name, lead_id, resolved_tenant_id,
            extra={
                "lead_id": lead_id,
                "channel": channel.name,
                "tenant_id": resolved_tenant_id,
            },
        )

        result = await channel.send(notification)
        if result:
            inc_counter("crew_fallback_sent", tenant_id=resolved_tenant_id)
        return result

    except Exception:
        logger.error(
            "Failed to send crew fallback: lead_id=%s, tenant=%s",
            lead_id, resolved_tenant_id,
            exc_info=True,
        )
        inc_counter("crew_fallback_failed", tenant_id=resolved_tenant_id)
        return False
