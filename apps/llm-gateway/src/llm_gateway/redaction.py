from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

BEARER_TOKEN_PATTERN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"
)

API_KEY_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key)"
    r"\s*[:=]\s*[^\s,;]+"
)

PASSWORD_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd)\s*[:=]\s*[^\s,;]+"
)

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-"
    r"[0-9a-fA-F]{12}\b"
)

UNSAFE_LOG_FIELDS = {
    "prompt",
    "prompt_template",
    "variables",
    "output",
    "output_text",
    "response_text",
}


def redact_text(value: str, *, preserve_request_id: str | None = None) -> str:
    """Return text with known sensitive patterns replaced."""

    redacted = EMAIL_PATTERN.sub(REDACTED, value)
    redacted = BEARER_TOKEN_PATTERN.sub(f"Bearer {REDACTED}", redacted)
    redacted = API_KEY_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED}",
        redacted,
    )
    redacted = PASSWORD_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED}",
        redacted,
    )

    def replace_uuid(match: re.Match[str]) -> str:
        token = match.group(0)
        if preserve_request_id is not None and token == preserve_request_id:
            return token
        return REDACTED

    return UUID_PATTERN.sub(replace_uuid, redacted)


def safe_log_metadata(
    values: Mapping[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Build log-safe metadata.

    Raw prompts, variables, and generated outputs are omitted entirely.
    String values are redacted before being returned.
    """

    safe: dict[str, Any] = {}

    for key, value in values.items():
        if key in UNSAFE_LOG_FIELDS:
            continue

        if key == "request_id":
            safe[key] = str(value)
            continue

        if isinstance(value, str):
            safe[key] = redact_text(
                value,
                preserve_request_id=request_id,
            )
        elif isinstance(value, bool | int | float) or value is None:
            safe[key] = value
        else:
            safe[key] = f"<{type(value).__name__}>"

    return safe
