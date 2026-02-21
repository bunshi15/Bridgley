# app/admin/errors.py
"""
Typed domain errors for the admin application service.

Each error maps to a specific HTTP status code.  The transport layer
catches ``AdminError`` subtypes and converts them to ``HTTPException``
without embedding business logic in the route handlers.
"""
from __future__ import annotations


class AdminError(Exception):
    """Base class for all admin domain errors."""

    status_code: int = 500

    def __init__(self, detail: str = "Internal error"):
        self.detail = detail
        super().__init__(detail)


class ValidationError(AdminError):
    """Invalid request payload (400)."""

    status_code = 400


class NotFoundError(AdminError):
    """Resource not found (404)."""

    status_code = 404


class ConflictError(AdminError):
    """Duplicate or conflicting resource (409)."""

    status_code = 409
