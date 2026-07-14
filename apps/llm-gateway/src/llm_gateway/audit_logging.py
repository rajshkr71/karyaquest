from __future__ import annotations

import json
import logging
from typing import Any

from llm_gateway.redaction import safe_log_metadata

AUDIT_LOGGER_NAME = "llm_gateway.audit"
AUDIT_SCHEMA_VERSION = 1
AUDIT_SERVICE = "llm-gateway"

logger = logging.getLogger(AUDIT_LOGGER_NAME)


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
