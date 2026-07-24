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
SAFE_ERROR_REASONS = {
    "agent_api_connection_error",
    "agent_api_invalid_json",
    "agent_api_timeout",
    "job_not_found",
    "malformed_claim_response",
    "malformed_job_response",
    "malformed_resume_response",
    "source_resume_id_missing",
    "source_resume_not_found",
}


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

    def get_job(self, job_id: str) -> dict[str, Any]: ...

    def get_resume(self, resume_id: str) -> dict[str, Any]: ...

    def complete_request(self, request_id: str, claim_token: str) -> dict[str, Any]: ...

    def fail_request(
        self,
        request_id: str,
        claim_token: str,
        failure_reason: str,
    ) -> dict[str, Any]: ...


class PlaceholderGenerator(Protocol):
    def __call__(self, generation_input: GenerationInput) -> None: ...


@dataclass(frozen=True)
class GenerationInput:
    request_id: str
    job_id: str
    resume_id: str
    job_title: str
    company: str
    job_description: str
    required_skills: list[Any]
    preferred_skills: list[Any]
    source_resume_content: str


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

    def get_job(self, job_id: str) -> dict[str, Any]:
        try:
            return self._request("GET", f"/jobs/{job_id}")
        except WorkerRuntimeError as exc:
            if exc.reason == "agent_api_http_404":
                raise WorkerRuntimeError("job_not_found") from exc
            raise

    def get_resume(self, resume_id: str) -> dict[str, Any]:
        try:
            return self._request("GET", f"/resumes/{resume_id}")
        except WorkerRuntimeError as exc:
            if exc.reason == "agent_api_http_404":
                raise WorkerRuntimeError("source_resume_not_found") from exc
            raise

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


def placeholder_generation(generation_input: GenerationInput) -> None:
    """Metadata-only placeholder; real generation is intentionally out of scope."""


def _required_string(record: dict[str, Any], field: str, record_type: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise WorkerRuntimeError(f"malformed_{record_type}_response")
    return value


def _required_list(record: dict[str, Any], field: str, record_type: str) -> list[Any]:
    value = record.get(field)
    if not isinstance(value, list):
        raise WorkerRuntimeError(f"malformed_{record_type}_response")
    return value


def load_generation_input(
    client: AgentApiClient,
    claimed: dict[str, Any],
) -> GenerationInput:
    request_id = _required_string(claimed, "id", "claim")
    job_id = _required_string(claimed, "job_id", "claim")
    resume_id = claimed.get("resume_id")
    if not isinstance(resume_id, str) or not resume_id.strip():
        raise WorkerRuntimeError("source_resume_id_missing")

    job = client.get_job(job_id)
    if not isinstance(job, dict):
        raise WorkerRuntimeError("malformed_job_response")
    resume = client.get_resume(resume_id)
    if not isinstance(resume, dict):
        raise WorkerRuntimeError("malformed_resume_response")
    if _required_string(job, "id", "job") != job_id:
        raise WorkerRuntimeError("malformed_job_response")
    if _required_string(resume, "id", "resume") != resume_id:
        raise WorkerRuntimeError("malformed_resume_response")

    return GenerationInput(
        request_id=request_id,
        job_id=job_id,
        resume_id=resume_id,
        job_title=_required_string(job, "title", "job"),
        company=_required_string(job, "company", "job"),
        job_description=_required_string(job, "description", "job"),
        required_skills=_required_list(job, "required_skills", "job"),
        preferred_skills=_required_list(job, "preferred_skills", "job"),
        source_resume_content=_required_string(resume, "content", "resume"),
    )


def safe_error_reason(exc: Exception) -> str:
    if isinstance(exc, WorkerRuntimeError) and (
        exc.reason in SAFE_ERROR_REASONS
        or re.fullmatch(r"agent_api_http_\d{3}", exc.reason)
    ):
        return exc.reason
    return "generation_failed"


def validate_claim_response(
    claimed: Any,
    request_id: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(claimed, dict):
        raise WorkerRuntimeError("malformed_claim_response")
    claimed_id = claimed.get("id")
    claim_token = claimed.get("claim_token")
    if (
        not isinstance(claimed_id, str)
        or not claimed_id.strip()
        or claimed_id != request_id
        or not isinstance(claim_token, str)
        or not claim_token.strip()
    ):
        raise WorkerRuntimeError("malformed_claim_response")
    return claimed, claim_token


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
            error=safe_error_reason(exc),
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
        claimed, claim_token = validate_claim_response(
            client.claim_request(request_id, worker_id),
            request_id,
        )
    except ClaimConflict:
        log_event("resume_generation.claim_conflict", request_id=request_id)
        return EXIT_SUCCESS
    except Exception as exc:
        log_event(
            "resume_generation.claim_failed",
            request_id=request_id,
            error=safe_error_reason(exc),
        )
        return EXIT_CLAIM_FAILED

    try:
        generation_input = load_generation_input(client, claimed)
        generator(generation_input)
    except Exception as exc:
        failure_reason = safe_error_reason(exc)
        try:
            client.fail_request(request_id, claim_token, failure_reason)
        except Exception as fail_exc:
            log_event(
                "resume_generation.fail_request_failed",
                request_id=request_id,
                original_failure_reason=failure_reason,
                error=safe_error_reason(fail_exc),
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
            error=safe_error_reason(exc),
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
