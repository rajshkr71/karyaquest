from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("resume_generator_worker")


class ClaimConflict(Exception):
    """Raised when another worker has already claimed the request."""


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
            raise
        if not response_body:
            return {}
        return json.loads(response_body)


def placeholder_generation(request: dict[str, Any]) -> None:
    """Metadata-only placeholder; real generation is intentionally out of scope."""


def log_event(event: str, **metadata: Any) -> None:
    safe_metadata = {
        key: value for key, value in metadata.items() if key != "claim_token"
    }
    LOGGER.info(json.dumps({"event": event, **safe_metadata}, sort_keys=True))


def run_once(
    client: AgentApiClient,
    *,
    worker_id: str,
    generator: PlaceholderGenerator = placeholder_generation,
) -> int:
    requests = client.list_requests()
    queued = next(
        (request for request in requests if request.get("status") == "queued"),
        None,
    )
    if queued is None:
        log_event("resume_generation.no_queued_request")
        return 0

    request_id = str(queued["id"])
    log_event("resume_generation.claim_attempt", request_id=request_id)
    try:
        claimed = client.claim_request(request_id, worker_id)
    except ClaimConflict:
        log_event("resume_generation.claim_conflict", request_id=request_id)
        return 0

    claim_token = claimed["claim_token"]
    try:
        generator(claimed)
    except Exception as exc:
        failure_reason = str(exc) or exc.__class__.__name__
        client.fail_request(request_id, claim_token, failure_reason)
        log_event(
            "resume_generation.failed",
            request_id=request_id,
            failure_reason=failure_reason,
        )
        return 1

    client.complete_request(request_id, claim_token)
    log_event("resume_generation.completed", request_id=request_id)
    return 0


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
