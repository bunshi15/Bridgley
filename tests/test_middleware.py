# tests/test_middleware.py
"""Tests for app/transport/middleware.py — request ID, error handling."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.transport.middleware import (
    RequestIDMiddleware,
    ErrorHandlingMiddleware,
)


def _build_app(raise_for: set[str] | None = None):
    """Build a minimal FastAPI app with middleware for testing."""
    app = FastAPI()
    # Order matters: ErrorHandling wraps RequestID
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    raise_for = raise_for or set()

    @app.get("/test")
    def test_endpoint():
        if "/test" in raise_for:
            raise RuntimeError("boom")
        return {"ok": True}

    @app.post("/webhooks/twilio")
    def twilio_endpoint():
        if "/webhooks/twilio" in raise_for:
            raise RuntimeError("twilio boom")
        return {"ok": True}

    @app.post("/webhooks/meta")
    def meta_endpoint():
        if "/webhooks/meta" in raise_for:
            raise RuntimeError("meta boom")
        return {"ok": True}

    return app


# ============================================================================
# RequestIDMiddleware
# ============================================================================

class TestRequestIDMiddleware:
    def test_generates_request_id(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        # Should be a UUID-style string
        rid = resp.headers["X-Request-ID"]
        assert len(rid) >= 32  # UUID has 36 chars with dashes

    def test_preserves_existing_request_id(self):
        app = _build_app()
        client = TestClient(app)
        custom_id = "my-custom-request-id-123"
        resp = client.get("/test", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == custom_id


# ============================================================================
# ErrorHandlingMiddleware
# ============================================================================

class TestErrorHandlingMiddleware:
    def test_normal_request_passes_through(self):
        app = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_twilio_error_returns_twiml_200(self):
        app = _build_app(raise_for={"/webhooks/twilio"})
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/webhooks/twilio")
        assert resp.status_code == 200
        assert "application/xml" in resp.headers.get("content-type", "")
        assert "<Response>" in resp.text

    def test_meta_error_returns_json_200(self):
        app = _build_app(raise_for={"/webhooks/meta"})
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/webhooks/meta")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_generic_error_returns_500(self):
        app = _build_app(raise_for={"/test"})
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert "request_id" in data
