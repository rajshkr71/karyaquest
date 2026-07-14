from __future__ import annotations

import json
import logging
from typing import Any

from llm_gateway.redaction import safe_log_metadata

AUDIT_LOGGER_NAME = "llm_gateway.audit"
AUDIT_SCHEMA_VERSION = 1
AUDIT_SERVICE = "llm-gateway"
AUDIT_HANDLER_MARKER = "_llm_gateway_audit_handler"


def _audit_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    setattr(handler, AUDIT_HANDLER_MARKER, True)
    return handler


def configure_audit_logger() -> logging.Logger:
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    dedicated_handlers = [
        handler
        for handler in audit_logger.handlers
        if getattr(handler, AUDIT_HANDLER_MARKER, False)
    ]
    if not dedicated_handlers:
        audit_logger.addHandler(_audit_handler())
    else:
        for handler in dedicated_handlers[1:]:
            audit_logger.removeHandler(handler)

    return audit_logger


logger = configure_audit_logger()


def log_audit_event(
    event: str,
    *,
    level: int = logging.INFO,
    **metadata: Any,
) -> None:
    """Emit one content-safe JSON audit event without affecting requests."""

    try:
        request_id = metadata.get("request_id")
        safe_metadata = safe_log_metadata(
            metadata,
            request_id=str(request_id) if request_id is not None else None,
        )
        record = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "service": AUDIT_SERVICE,
            "event": event,
            "outcome": safe_metadata.pop("outcome", "unknown"),
            **safe_metadata,
        }
        message = json.dumps(
            record,
            allow_nan=False,
            separators=(",", ":"),
        )
        logger.log(level, message)
    except Exception:
        return
