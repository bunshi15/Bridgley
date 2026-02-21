# app/transport/middleware.py
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from app.infra.logging_config import get_logger, LogContext

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request for tracing"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all incoming requests and responses"""

    def __init__(self, app: ASGIApp, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "unknown")
        start_time = time.time()

        # Log request
        log_ctx = LogContext(logger, request_id=request_id)
        log_ctx.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
            }
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            log_ctx.info(
                f"Request completed: {request.method} {request.url.path} "
                f"status={response.status_code} duration={duration_ms:.2f}ms",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )

            return response

        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            log_ctx.error(
                f"Request failed: {request.method} {request.url.path} "
                f"error={exc.__class__.__name__} duration={duration_ms:.2f}ms",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "error_type": exc.__class__.__name__,
                    "duration_ms": duration_ms,
                },
                exc_info=True
            )
            raise


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch and format unhandled exceptions"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "unknown")

            logger.error(
                f"Unhandled exception: {exc.__class__.__name__}: {exc}",
                extra={"request_id": request_id},
                exc_info=True
            )

            # For Twilio webhook, return TwiML error response
            if request.url.path == "/webhooks/twilio":
                from fastapi.responses import PlainTextResponse
                error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>An error occurred. Please try again.</Message>
</Response>"""
                return PlainTextResponse(
                    content=error_twiml,
                    status_code=200,  # Return 200 so Twilio doesn't retry
                    media_type="application/xml"
                )

            # For Meta webhook, return 200 JSON to prevent retries
            if request.url.path == "/webhooks/meta":
                from fastapi.responses import JSONResponse as _JSONResponse
                return _JSONResponse(
                    content={"status": "error"},
                    status_code=200,  # Return 200 so Meta doesn't retry
                )

            # Return generic JSON error for other endpoints
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "request_id": request_id,
                }
            )