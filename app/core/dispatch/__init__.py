# app/core/dispatch/__init__.py
"""
Dispatch Layer (EPIC B) — isolated from bot engines.

This package handles crew-facing operations:
- ``crew_view`` — CrewLeadView builder (PII-safe allowlist DTO)
- ``services`` — Notification delivery for crew fallback
- ``jobs`` — Job handlers for dispatch worker role

Dispatch code must NOT import bot handler modules.
Dispatch jobs run under ``WORKER_ROLE=dispatch`` (or ``all``).
"""
