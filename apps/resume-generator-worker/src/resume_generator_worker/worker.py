from __future__ import annotations

import json
import logging
import os
import re
import socket
from json import JSONDecodeError
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("resume_generator_worker")
EXIT_SUCCESS = 0
EXIT_GENERATION_FAILED = 1
EXIT_LIST_FAILED = 2
EXIT_CLAIM_FAILED = 3
EXIT_COMPLETE_FAILED = 4
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class ClaimConflict(Exception):
    """Raised when another worker has already claimed the request."""


class WorkerRuntimeError(Exception):
    """Raised for safe, expected one-shot worker failures."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AgentApiClient(Protocol):
    def list_requests(self) -> list[dict[str, Any]]: ...

    def claim_request(self, request_id: str, worker_id: str) -> dict[str, Any]: ...

    def complete_request(self, request_id: str, claim_token: str) -> dict[str, Any]: ...

    def fail_request(
        self,
        request_id: str,
        claim_token: str,
        failure_reason: str,
    ) -> dict[str, Any]: ...


class PlaceholderGenerator(Protocol):
    def __call__(self, request: dict[str, Any]) -> None: ...


@dataclass
class HttpAgentApiClient:
    base_url: str
    timeout_seconds: float = 10.0

    def list_requests(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/resume-generation-requests")
        if isinstance(data, list):
            return data
        return data.get("items", [])

    def claim_request(self, request_id: str, worker_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/resume-generation-requests/{request_id}/claim",
            {"worker_id": worker_id},
        )

    def complete_request(self, request_id: str, claim_token: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/resume-generation-requests/{request_id}/complete",
            {"claim_token": claim_token},
        )

    def fail_request(
        self,
        request_id: str,
        claim_token: str,
        failure_reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/resume-generation-requests/{request_id}/fail",
            {"claim_token": claim_token, "failure_reason": failure_reason},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code == 409 and path.endswith("/claim"):
                raise ClaimConflict from exc
            raise WorkerRuntimeError(f"agent_api_http_{exc.code}") from exc
        except TimeoutError as exc:
            raise WorkerRuntimeError("agent_api_timeout") from exc
        except socket.timeout as exc:
            raise WorkerRuntimeError("agent_api_timeout") from exc
        except URLError as exc:
            raise WorkerRuntimeError("agent_api_connection_error") from exc
        if not response_body:
            return {}
        try:
            return json.loads(response_body)
        except JSONDecodeError as exc:
            raise WorkerRuntimeError("agent_api_invalid_json") from exc


def placeholder_generation(request: dict[str, Any]) -> None:
    """Metadata-only placeholder; real generation is intentionally out of scope."""


def sanitize_text(value: Any, *, preserve_uuid: bool = False) -> str:
    text = str(value).strip() or value.__class__.__name__
    replacements = [
        "claim_token",
        "token",
        "password",
        "secret",
        "profile content",
        "resume content",
    ]
    lowered = text.lower()
    if any(marker in lowered for marker in replacements):
        return "[redacted]"
    if not preserve_uuid:
        text = UUID_PATTERN.sub("[redacted-id]", text)
    if len(text) > 200:
        return f"{text[:197]}..."
    return text


def log_event(event: str, **metadata: Any) -> None:
    safe_metadata = {
        key: sanitize_text(value, preserve_uuid=key == "request_id")
        for key, value in metadata.items()
        if key != "claim_token"
    }
    LOGGER.info(json.dumps({"event": event, **safe_metadata}, sort_keys=True))


def run_once(
    client: AgentApiClient,
    *,
    worker_id: str,
    generator: PlaceholderGenerator = placeholder_generation,
) -> int:
    try:
        requests = client.list_requests()
    except Exception as exc:
        log_event(
            "resume_generation.list_failed",
            error=sanitize_text(exc),
        )
        return EXIT_LIST_FAILED

    queued = next(
        (request for request in requests if request.get("status") == "queued"),
        None,
    )
    if queued is None:
        log_event("resume_generation.no_queued_request")
        return EXIT_SUCCESS

    request_id = str(queued["id"])
    log_event("resume_generation.claim_attempt", request_id=request_id)
    try:
        claimed = client.claim_request(request_id, worker_id)
    except ClaimConflict:
        log_event("resume_generation.claim_conflict", request_id=request_id)
        return EXIT_SUCCESS
    except Exception as exc:
        log_event(
            "resume_generation.claim_failed",
            request_id=request_id,
            error=sanitize_text(exc),
        )
        return EXIT_CLAIM_FAILED

    claim_token = claimed["claim_token"]
    try:
        generator(claimed)
    except Exception as exc:
        failure_reason = sanitize_text(exc)
        try:
            client.fail_request(request_id, claim_token, failure_reason)
        except Exception as fail_exc:
            log_event(
                "resume_generation.fail_request_failed",
                request_id=request_id,
                original_failure_reason=failure_reason,
                error=sanitize_text(fail_exc),
            )
            return EXIT_GENERATION_FAILED
        log_event(
            "resume_generation.failed",
            request_id=request_id,
            failure_reason=failure_reason,
        )
        return EXIT_GENERATION_FAILED

    try:
        client.complete_request(request_id, claim_token)
    except Exception as exc:
        log_event(
            "resume_generation.complete_failed",
            request_id=request_id,
            error=sanitize_text(exc),
        )
        return EXIT_COMPLETE_FAILED
    log_event("resume_generation.completed", request_id=request_id)
    return EXIT_SUCCESS


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    client = HttpAgentApiClient(
        os.getenv("AGENT_API_URL", "http://agent-api:8000"),
        timeout_seconds=float(os.getenv("AGENT_API_TIMEOUT_SECONDS", "10")),
    )
    worker_id = os.getenv("WORKER_ID", "resume-generator-worker")
    return run_once(client, worker_id=worker_id)


if __name__ == "__main__":
    raise SystemExit(main())
