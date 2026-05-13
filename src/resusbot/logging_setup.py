import hashlib
import logging
import sys
from typing import Any

import structlog


def _redact_telegram_id(logger: Any, method: Any, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Substitui telegram_id por hash truncado para evitar armazenar PII nos logs."""
    if "telegram_id" in event_dict:
        raw = str(event_dict["telegram_id"])
        event_dict["telegram_id"] = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return event_dict


def _drop_sensitive_keys(logger: Any, method: Any, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in ("token", "password", "secret", "api_key"):
        if key in event_dict:
            event_dict[key] = "***"
    return event_dict


def setup_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_telegram_id,
        _drop_sensitive_keys,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if log_level == "DEBUG"
        else structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Silencia loggers externos ruidosos
    for noisy in ("httpx", "httpcore", "telegram"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
