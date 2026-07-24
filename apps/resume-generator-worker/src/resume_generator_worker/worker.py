from __future__ import annotations

import json
import logging
import os
import re
import socket
import uuid
from json import JSONDecodeError
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from resume_generator_worker.storage import (
    ArtifactMetadata,
    ArtifactStorageError,
    ArtifactStore,
    MinioArtifactStore,
    StoredArtifact,
    persist_artifact,
    validate_storage_configuration,
)

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
    "artifact_serialization_failed",
    "artifact_storage_configuration_error",
    "artifact_storage_conflict",
    "artifact_storage_connection_error",
    "artifact_storage_invalid_response",
    "artifact_storage_timeout",
    "job_not_found",
    "llm_gateway_connection_error",
    "llm_gateway_invalid_json",
    "llm_gateway_malformed_response",
    "llm_gateway_timeout",
    "malformed_claim_response",
    "malformed_job_response",
    "malformed_resume_response",
    "source_resume_id_missing",
    "source_resume_not_found",
    "resume_generation_unsupported_claims",
}
STORAGE_ERROR_REASONS = {
    "artifact_storage_connection_error",
    "artifact_storage_timeout",
    "artifact_storage_invalid_response",
    "artifact_storage_conflict",
    "artifact_serialization_failed",
    "artifact_storage_configuration_error",
}
TRUTHFUL_RESUME_INSTRUCTIONS = """Tailor the resume for the supplied job.
Use only facts present in the source resume.
Do not invent employers.
Do not invent projects.
Do not invent certifications.
Do not invent education.
Do not inflate years of experience.
Preserve truthful dates and technologies.
Report unsupported claims in unsupported_claims rather than including them.
Return only a JSON object with tailored_resume_content, change_summary,
source_facts_used, and unsupported_claims."""


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

    def complete_request(
        self,
        request_id: str,
        claim_token: str,
        artifact: ArtifactMetadata,
    ) -> dict[str, Any]: ...

    def get_artifact(
        self, request_id: str, job_id: str, source_resume_id: str
    ) -> dict[str, Any] | None: ...

    def fail_request(
        self,
        request_id: str,
        claim_token: str,
        failure_reason: str,
    ) -> dict[str, Any]: ...


class ResumeGenerator(Protocol):
    def __call__(
        self,
        request: ResumeGenerationRequest,
    ) -> LlmGenerationExecution | ResumeGenerationResult | None: ...


@dataclass(frozen=True)
class ResumeGenerationRequest:
    request_id: str
    job_id: str
    resume_id: str
    job_title: str
    company: str
    job_description: str
    required_skills: list[Any]
    preferred_skills: list[Any]
    source_resume_content: str


GenerationInput = ResumeGenerationRequest


@dataclass(frozen=True)
class ResumeGenerationResult:
    tailored_resume_content: str
    change_summary: list[str]
    source_facts_used: list[str]
    unsupported_claims: list[str]


@dataclass(frozen=True)
class LlmGenerationExecution:
    result: ResumeGenerationResult
    provider: str
    model: str
    model_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    finish_reason: str


class LlmGatewayClient(Protocol):
    def generate(self, request: ResumeGenerationRequest) -> LlmGenerationExecution: ...


@dataclass
class HttpLlmGatewayClient:
    base_url: str
    provider: str
    model: str
    temperature: float = 0.2
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0

    def generate(self, request: ResumeGenerationRequest) -> LlmGenerationExecution:
        payload = {
            "request_id": request.request_id,
            "task_type": "resume_generation",
            "prompt_template": TRUTHFUL_RESUME_INSTRUCTIONS,
            "variables": asdict(request),
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "metadata": {
                "job_id": request.job_id,
                "resume_id": request.resume_id,
            },
        }
        http_request = Request(
            f"{self.base_url.rstrip('/')}/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except (TimeoutError, socket.timeout) as exc:
            raise WorkerRuntimeError("llm_gateway_timeout") from exc
        except (HTTPError, URLError) as exc:
            raise WorkerRuntimeError("llm_gateway_connection_error") from exc
        try:
            gateway_response = json.loads(response_body)
        except JSONDecodeError as exc:
            raise WorkerRuntimeError("llm_gateway_invalid_json") from exc
        envelope = self._validate_envelope(gateway_response, request.request_id)
        output_text = envelope["output_text"]
        try:
            structured_output = json.loads(output_text)
        except JSONDecodeError as exc:
            raise WorkerRuntimeError("llm_gateway_malformed_response") from exc
        result = validate_generation_result(structured_output)
        return LlmGenerationExecution(
            result=result,
            provider=envelope["provider"],
            model=envelope["model"],
            model_version=envelope["model_version"],
            input_tokens=envelope["input_tokens"],
            output_tokens=envelope["output_tokens"],
            latency_ms=envelope["latency_ms"],
            finish_reason=envelope["finish_reason"],
        )

    def _validate_envelope(self, response: Any, request_id: str) -> dict[str, Any]:
        expected_fields = {
            "request_id",
            "provider",
            "model",
            "model_version",
            "output_text",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "finish_reason",
            "redactions_applied",
        }
        if not isinstance(response, dict) or set(response) != expected_fields:
            raise WorkerRuntimeError("llm_gateway_malformed_response")
        if (
            response["request_id"] != request_id
            or response["provider"] != self.provider
            or response["model"] != self.model
        ):
            raise WorkerRuntimeError("llm_gateway_malformed_response")
        if any(
            not isinstance(response[field], str) or not response[field].strip()
            for field in ("model_version", "output_text", "finish_reason")
        ):
            raise WorkerRuntimeError("llm_gateway_malformed_response")
        if any(
            type(response[field]) is not int or response[field] < 0
            for field in ("input_tokens", "output_tokens", "latency_ms")
        ):
            raise WorkerRuntimeError("llm_gateway_malformed_response")
        redactions = response["redactions_applied"]
        if not isinstance(redactions, list) or any(
            not isinstance(item, str) for item in redactions
        ):
            raise WorkerRuntimeError("llm_gateway_malformed_response")
        return response


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

    def complete_request(
        self,
        request_id: str,
        claim_token: str,
        artifact: ArtifactMetadata,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/resume-generation-requests/{request_id}/complete",
            {"claim_token": claim_token, "artifact": asdict(artifact)},
        )

    def get_artifact(
        self, request_id: str, job_id: str, source_resume_id: str
    ) -> dict[str, Any] | None:
        try:
            data = self._request(
                "GET", f"/resume-generation-requests/{request_id}/artifact"
            )
        except WorkerRuntimeError as exc:
            if exc.reason == "agent_api_http_404":
                return None
            raise
        return validate_artifact_response(data, request_id, job_id, source_resume_id)

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


def placeholder_generation(request: ResumeGenerationRequest) -> None:
    """Metadata-only placeholder; real generation is intentionally out of scope."""


def validate_generation_result(response: Any) -> ResumeGenerationResult:
    expected_fields = {
        "tailored_resume_content",
        "change_summary",
        "source_facts_used",
        "unsupported_claims",
    }
    if not isinstance(response, dict) or set(response) != expected_fields:
        raise WorkerRuntimeError("llm_gateway_malformed_response")
    tailored_resume_content = response["tailored_resume_content"]
    if (
        not isinstance(tailored_resume_content, str)
        or not tailored_resume_content.strip()
    ):
        raise WorkerRuntimeError("llm_gateway_malformed_response")
    list_fields = {
        field: response[field]
        for field in ("change_summary", "source_facts_used", "unsupported_claims")
    }
    if any(
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        for value in list_fields.values()
    ):
        raise WorkerRuntimeError("llm_gateway_malformed_response")
    if list_fields["unsupported_claims"]:
        raise WorkerRuntimeError("resume_generation_unsupported_claims")
    return ResumeGenerationResult(
        tailored_resume_content=tailored_resume_content,
        change_summary=list_fields["change_summary"],
        source_facts_used=list_fields["source_facts_used"],
        unsupported_claims=list_fields["unsupported_claims"],
    )


def validate_generation_execution(execution: Any) -> LlmGenerationExecution:
    if not isinstance(execution, LlmGenerationExecution):
        raise WorkerRuntimeError("llm_gateway_malformed_response")
    result_value = (
        asdict(execution.result)
        if isinstance(execution.result, ResumeGenerationResult)
        else execution.result
    )
    result = validate_generation_result(result_value)
    if any(
        not isinstance(getattr(execution, field), str)
        or not getattr(execution, field).strip()
        for field in ("provider", "model", "model_version", "finish_reason")
    ) or any(
        type(getattr(execution, field)) is not int or getattr(execution, field) < 0
        for field in ("input_tokens", "output_tokens", "latency_ms")
    ):
        raise WorkerRuntimeError("llm_gateway_malformed_response")
    return LlmGenerationExecution(
        result=result,
        provider=execution.provider,
        model=execution.model,
        model_version=execution.model_version,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        latency_ms=execution.latency_ms,
        finish_reason=execution.finish_reason,
    )


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
) -> ResumeGenerationRequest:
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

    return ResumeGenerationRequest(
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


def artifact_metadata_matches(
    actual: dict[str, Any] | None,
    expected: ArtifactMetadata,
    request_id: str,
    job_id: str,
    source_resume_id: str,
) -> bool:
    try:
        validated = validate_artifact_response(
            actual, request_id, job_id, source_resume_id
        )
    except WorkerRuntimeError:
        return False
    return all(validated[key] == value for key, value in asdict(expected).items())


def validate_artifact_response(
    response: Any,
    request_id: str,
    job_id: str,
    source_resume_id: str,
) -> dict[str, Any]:
    metadata_fields = set(ArtifactMetadata.__dataclass_fields__)
    expected_fields = metadata_fields | {
        "id", "request_id", "job_id", "source_resume_id", "created_at"
    }
    if not isinstance(response, dict) or set(response) != expected_fields:
        raise WorkerRuntimeError("agent_api_invalid_json")
    try:
        uuid.UUID(response["id"])
    except (AttributeError, TypeError, ValueError):
        raise WorkerRuntimeError("agent_api_invalid_json") from None
    if (
        not isinstance(response["id"], str)
        or not response["id"].strip()
        or response["request_id"] != request_id
        or response["job_id"] != job_id
        or response["source_resume_id"] != source_resume_id
    ):
        raise WorkerRuntimeError("agent_api_invalid_json")
    string_fields = {
        "storage_bucket", "storage_key", "content_type", "provider", "model",
        "model_version", "finish_reason", "created_at",
    }
    if any(
        not isinstance(response[field], str) or not response[field].strip()
        for field in string_fields
    ):
        raise WorkerRuntimeError("agent_api_invalid_json")
    if not isinstance(response["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", response["sha256"]
    ):
        raise WorkerRuntimeError("agent_api_invalid_json")
    if any(
        type(response[field]) is not int or response[field] < 0
        for field in ("size_bytes", "input_tokens", "output_tokens", "latency_ms")
    ):
        raise WorkerRuntimeError("agent_api_invalid_json")
    return response


def safe_storage_reason(exc: Exception) -> str:
    if isinstance(exc, ArtifactStorageError) and exc.reason in STORAGE_ERROR_REASONS:
        return exc.reason
    return "artifact_storage_invalid_response"


def fail_generation_request(
    client: AgentApiClient,
    request_id: str,
    claim_token: str,
    reason: str,
) -> int:
    try:
        client.fail_request(request_id, claim_token, reason)
    except Exception as exc:
        log_event(
            "resume_generation.fail_request_failed",
            request_id=request_id,
            original_failure_reason=reason,
            error=safe_error_reason(exc),
        )
    else:
        log_event(
            "resume_generation.failed",
            request_id=request_id,
            failure_reason=reason,
        )
    return EXIT_GENERATION_FAILED


def remove_created_artifact(
    store: ArtifactStore,
    stored: StoredArtifact,
    request_id: str,
) -> None:
    if not stored.created:
        return
    try:
        store.remove(stored.metadata.storage_bucket, stored.metadata.storage_key)
    except Exception as exc:
        reason = safe_storage_reason(exc)
        log_event(
            "resume_generation.artifact_cleanup_failed",
            request_id=request_id,
            error=reason,
        )


def run_once(
    client: AgentApiClient,
    *,
    worker_id: str,
    generator: ResumeGenerator | None = None,
    llm_client: LlmGatewayClient | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_bucket: str = "generated-documents",
) -> int:
    generate = llm_client.generate if llm_client is not None else generator
    if generate is None:
        generate = placeholder_generation
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
        generation_result = generate(generation_input)
        execution = (
            validate_generation_execution(generation_result)
            if isinstance(generation_result, LlmGenerationExecution)
            else None
        )
        result = execution.result if execution else generation_result
        if result is not None:
            if isinstance(result, ResumeGenerationResult):
                result = asdict(result)
            validate_generation_result(result)
    except Exception as exc:
        failure_reason = safe_error_reason(exc)
        return fail_generation_request(client, request_id, claim_token, failure_reason)

    stored = None
    if artifact_store is not None:
        if execution is None:
            return fail_generation_request(
                client, request_id, claim_token, "llm_gateway_malformed_response"
            )
        try:
            stored = persist_artifact(
                artifact_store,
                generation_input,
                execution,
                artifact_bucket,
            )
        except Exception as exc:
            reason = safe_storage_reason(exc)
            return fail_generation_request(client, request_id, claim_token, reason)

    try:
        if stored is None:
            client.complete_request(request_id, claim_token)  # type: ignore[call-arg]
        else:
            client.complete_request(request_id, claim_token, stored.metadata)
    except Exception as exc:
        reason = safe_error_reason(exc)
        if stored is not None and reason in {
            "agent_api_timeout",
            "agent_api_connection_error",
            "agent_api_http_409",
        }:
            try:
                reconciled = client.get_artifact(
                    request_id, generation_input.job_id, generation_input.resume_id
                )
                if reconciled is not None:
                    reconciled = validate_artifact_response(
                        reconciled,
                        request_id,
                        generation_input.job_id,
                        generation_input.resume_id,
                    )
            except Exception:
                reconciled = None
                reconciliation_uncertain = True
            else:
                reconciliation_uncertain = reconciled is None and reason != "agent_api_http_409"
            if artifact_metadata_matches(
                reconciled,
                stored.metadata,
                request_id,
                generation_input.job_id,
                generation_input.resume_id,
            ):
                log_event("resume_generation.completed", request_id=request_id)
                return EXIT_SUCCESS
            if reason == "agent_api_http_409" and not reconciliation_uncertain:
                remove_created_artifact(artifact_store, stored, request_id)
                fail_generation_request(
                    client,
                    request_id,
                    claim_token,
                    "artifact_storage_conflict",
                )
            else:
                log_event(
                    "resume_generation.manual_action_required",
                    request_id=request_id,
                    error=reason,
                )
            return EXIT_COMPLETE_FAILED
        if stored is not None:
            remove_created_artifact(artifact_store, stored, request_id)
            fail_generation_request(client, request_id, claim_token, reason)
        log_event(
            "resume_generation.complete_failed",
            request_id=request_id,
            error=reason,
        )
        return EXIT_COMPLETE_FAILED
    completion_metadata = {"request_id": request_id}
    if stored is not None:
        completion_metadata.update(
            asdict(stored.metadata) | {
                "created_or_reused": "created" if stored.created else "reused"
            }
        )
    log_event("resume_generation.completed", **completion_metadata)
    return EXIT_SUCCESS


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    try:
        minio_endpoint, minio_access_key, minio_secret_key, artifact_bucket = (
            validate_storage_configuration(
                os.getenv("MINIO_ENDPOINT"),
                os.getenv("MINIO_ACCESS_KEY"),
                os.getenv("MINIO_SECRET_KEY"),
                os.getenv("MINIO_BUCKET", "generated-documents"),
            )
        )
        minio_secure = parse_minio_secure(os.getenv("MINIO_SECURE", "false"))
        artifact_store = MinioArtifactStore(
            minio_endpoint,
            minio_access_key,
            minio_secret_key,
            secure=minio_secure,
        )
    except Exception:
        log_event(
            "resume_generation.configuration_failed",
            error="artifact_storage_configuration_error",
        )
        return EXIT_GENERATION_FAILED
    client = HttpAgentApiClient(
        os.getenv("AGENT_API_URL", "http://agent-api:8000"),
        timeout_seconds=float(os.getenv("AGENT_API_TIMEOUT_SECONDS", "10")),
    )
    llm_client = HttpLlmGatewayClient(
        os.environ["LLM_GATEWAY_URL"],
        provider=os.environ["LLM_GATEWAY_PROVIDER"],
        model=os.environ["LLM_GATEWAY_MODEL"],
        temperature=float(os.getenv("LLM_GATEWAY_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("LLM_GATEWAY_MAX_OUTPUT_TOKENS", "1024")),
        timeout_seconds=float(os.getenv("LLM_GATEWAY_TIMEOUT_SECONDS", "30")),
    )
    worker_id = os.getenv("WORKER_ID", "resume-generator-worker")
    return run_once(
        client,
        worker_id=worker_id,
        llm_client=llm_client,
        artifact_store=artifact_store,
        artifact_bucket=artifact_bucket,
    )


def parse_minio_secure(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ArtifactStorageError("artifact_storage_configuration_error")


if __name__ == "__main__":
    raise SystemExit(main())
