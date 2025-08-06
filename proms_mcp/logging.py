"""Centralized logging configuration for the MCP server."""

import logging

import structlog


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter that includes level for all logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "event": record.getMessage(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "timestamp": self.formatTime(record, self.datefmt),
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        import json

        return json.dumps(log_entry)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        from datetime import datetime

        dt = datetime.fromtimestamp(record.created)
        return dt.isoformat() + "Z"


def configure_logging() -> None:
    """Configure structured logging for the entire application."""
    import os

    # Get log level from environment variable
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    # Configure stdlib logging first with JSON formatting
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
    )

    # Set up a JSON handler for all loggers
    handler = logging.StreamHandler()
    handler.setFormatter(json_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # Remove existing handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Configure structlog to work with stdlib logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Don't render to JSON here - let the stdlib formatter handle it
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure specific loggers with custom JSON formatter for consistent level output
    custom_json_formatter = JSONFormatter()
    custom_handler = logging.StreamHandler()
    custom_handler.setFormatter(custom_json_formatter)

    # Configure all third-party logging levels to INFO for visibility (per updated SPECS.md)
    for logger_name in ["fastmcp", "mcp", "uvicorn", "uvicorn.error", "uvicorn.access"]:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(custom_handler)
        logger.setLevel(log_level)
        logger.propagate = False  # Don't propagate to root

    # Keep HTTP client logs at WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_uvicorn_log_config() -> dict:
    """Get uvicorn logging configuration that integrates with structlog."""
    return {
        "version": 1,
        "disable_existing_loggers": False,  # Keep our configured loggers
        "formatters": {
            "json": {
                "()": "proms_mcp.logging.JSONFormatter",
            },
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,  # Don't propagate to root logger
            },
            "uvicorn.error": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["default"],
                "level": "INFO",  # Changed to INFO for visibility
                "propagate": False,
            },
        },
    }
