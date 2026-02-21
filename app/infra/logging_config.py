# app/infra/logging_config.py
import logging
import sys
import json
from datetime import datetime, timezone
from typing import Any
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for production environments"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        if hasattr(record, "chat_id"):
            log_data["chat_id"] = record.chat_id
        if hasattr(record, "lead_id"):
            log_data["lead_id"] = record.lead_id
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Human-readable format for development"""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        reset = self.COLORS["RESET"]

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Build context string
        context_parts = []
        if hasattr(record, "tenant_id"):
            context_parts.append(f"tenant={record.tenant_id}")
        if hasattr(record, "chat_id"):
            # Mask phone numbers
            chat_id = record.chat_id
            if len(chat_id) > 6:
                chat_id = chat_id[:4] + "****" + chat_id[-2:]
            context_parts.append(f"chat={chat_id}")
        if hasattr(record, "lead_id"):
            context_parts.append(f"lead={record.lead_id}")

        context = f" [{' '.join(context_parts)}]" if context_parts else ""

        return (
            f"{color}[{timestamp}] {record.levelname:8}{reset} "
            f"{record.name}{context} - {record.getMessage()}"
        )


def setup_logging(level: str = "INFO", use_json: bool = False) -> None:
    """
    Configure application logging

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: If True, use JSON format (for production)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if use_json:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    logging.info(f"Logging configured: level={level}, json={use_json}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name"""
    return logging.getLogger(name)


# Context-aware logging helpers
class LogContext:
    """Add context to log records"""

    def __init__(
            self,
            logger: logging.Logger,
            tenant_id: str | None = None,
            chat_id: str | None = None,
            lead_id: str | None = None,
            request_id: str | None = None,
    ):
        self.logger = logger
        self.context = {
            k: v for k, v in {
                "tenant_id": tenant_id,
                "chat_id": chat_id,
                "lead_id": lead_id,
                "request_id": request_id,
            }.items() if v is not None
        }

    def _log(self, level: int, msg: str, *args, **kwargs):
        extra = kwargs.pop("extra", {})
        extra.update(self.context)
        self.logger.log(level, msg, *args, extra=extra, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)


def mask_coordinates(lat: float, lon: float) -> str:
    """Mask GPS coordinates for logging to prevent location spoofing.

    Example: ``mask_coordinates(32.794, 34.989)`` → ``"32.7**, 34.9**"``

    Shows only the first decimal digit (roughly ±10 km precision),
    which is enough for debugging without exposing exact user location.
    """
    return f"{lat:.1f}**, {lon:.1f}**"