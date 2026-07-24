from __future__ import annotations

import json
import logging
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src"),
)

import pytest

from resume_generator_worker import worker
from resume_generator_worker.worker import (
    ClaimConflict,
    EXIT_CLAIM_FAILED,
    EXIT_COMPLETE_FAILED,
    EXIT_GENERATION_FAILED,
    EXIT_LIST_FAILED,
    EXIT_SUCCESS,
    GenerationInput,
    HttpAgentApiClient,
    HttpLlmGatewayClient,
    ResumeGenerationResult,
    WorkerRuntimeError,
    run_once,
)


CLAIM_TOKEN = "78cd0b26-b30a-4cf6-8c1e-031a0036fc45"
REQUEST_ID = "2ecee968-87dc-43bf-bf6b-10b5c4cfd379"
JOB_ID = "e56ee8f6-9e6d-4d12-b826-bf69f4d545bf"
RESUME_ID = "fb936cab-0161-4780-b69d-bf6bc76a0119"


def job_record():
    return {
        "id": JOB_ID,
        "title": "Platform Engineer",
        "company": "Example Corp",
        "description": "Build reliable systems",
        "required_skills": ["Python", "PostgreSQL"],
        "preferred_skills": ["Kubernetes"],
    }


def resume_record():
    return {
        "id": RESUME_ID,
        "content": "Experienced platform engineer",
    }


def valid_generation_output(**overrides):
    output = {
        "tailored_resume_content": "Truthful tailored resume",
        "change_summary": ["Reordered skills"],
        "source_facts_used": ["Python experience"],
        "unsupported_claims": [],
    }
    return output | overrides


def gateway_envelope(output_text=None, **overrides):
    envelope = {
        "request_id": REQUEST_ID,
        "provider": "provider",
        "model": "model",
        "model_version": "model-v1",
        "output_text": output_text or json.dumps(valid_generation_output()),
        "input_tokens": 100,
        "output_tokens": 200,
        "latency_ms": 300,
        "finish_reason": "stop",
        "redactions_applied": [],
    }
    return envelope | overrides


class FakeLlmClient:
    def __init__(self, result=None, error=None):
        self.result = result or ResumeGenerationResult(**valid_generation_output())
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.result


class HttpResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class FakeClient:
    def __init__(
        self,
        requests=None,
        list_error=None,
        claim_error=None,
        complete_error=None,
        fail_error=None,
        job=None,
        resume=None,
        job_error=None,
        resume_error=None,
    ):
        self.requests = requests or []
        self.list_error = list_error
        self.claim_error = claim_error
        self.complete_error = complete_error
        self.fail_error = fail_error
        self.job = job_record() if job is None else job
        self.resume = resume_record() if resume is None else resume
        self.job_error = job_error
        self.resume_error = resume_error
        self.claims = []
        self.loaded_jobs = []
        self.loaded_resumes = []
        self.completed = []
        self.failed = []

    def list_requests(self):
        if self.list_error:
            raise self.list_error
        return self.requests

    def claim_request(self, request_id, worker_id):
        self.claims.append((request_id, worker_id))
        if self.claim_error:
            raise self.claim_error
        return {
            "id": request_id,
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "status": "processing",
            "claim_token": CLAIM_TOKEN,
        }

    def get_job(self, job_id):
        self.loaded_jobs.append(job_id)
        if self.job_error:
            raise self.job_error
        return self.job

    def get_resume(self, resume_id):
        self.loaded_resumes.append(resume_id)
        if self.resume_error:
            raise self.resume_error
        return self.resume

    def complete_request(self, request_id, claim_token):
        self.completed.append((request_id, claim_token))
        if self.complete_error:
            raise self.complete_error
        return {"id": request_id, "status": "completed"}

    def fail_request(self, request_id, claim_token, failure_reason):
        self.failed.append((request_id, claim_token, failure_reason))
        if self.fail_error:
            raise self.fail_error
        return {"id": request_id, "status": "failed"}


def queued_request():
    return {"id": REQUEST_ID, "status": "queued"}


def generation_request():
    return GenerationInput(
        request_id=REQUEST_ID,
        job_id=JOB_ID,
        resume_id=RESUME_ID,
        job_title="Platform Engineer",
        company="Example Corp",
        job_description="Build reliable systems",
        required_skills=["Python", "PostgreSQL"],
        preferred_skills=["Kubernetes"],
        source_resume_content="Experienced platform engineer",
    )


def test_no_queued_request_exits_successfully(caplog):
    client = FakeClient([{"id": REQUEST_ID, "status": "processing"}])

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_SUCCESS
    assert client.claims == []
    assert "resume_generation.no_queued_request" in caplog.text


def test_successful_claim_and_complete():
    client = FakeClient([queued_request()])
    received = []

    exit_code = run_once(client, worker_id="worker-a", generator=received.append)

    assert exit_code == EXIT_SUCCESS
    assert client.claims == [(REQUEST_ID, "worker-a")]
    assert client.completed == [(REQUEST_ID, CLAIM_TOKEN)]
    assert client.failed == []
    assert client.loaded_jobs == [JOB_ID]
    assert client.loaded_resumes == [RESUME_ID]
    assert received == [
        GenerationInput(
            request_id=REQUEST_ID,
            job_id=JOB_ID,
            resume_id=RESUME_ID,
            job_title="Platform Engineer",
            company="Example Corp",
            job_description="Build reliable systems",
            required_skills=["Python", "PostgreSQL"],
            preferred_skills=["Kubernetes"],
            source_resume_content="Experienced platform engineer",
        )
    ]


def test_claim_conflict_exits_safely():
    client = FakeClient([queued_request()], claim_error=ClaimConflict())

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_SUCCESS
    assert client.claims == [(REQUEST_ID, "worker-a")]
    assert client.completed == []
    assert client.failed == []


def test_list_request_http_failure_returns_non_zero(caplog):
    client = FakeClient(list_error=WorkerRuntimeError("agent_api_http_500"))

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_LIST_FAILED
    assert "resume_generation.list_failed" in caplog.text
    assert "agent_api_http_500" in caplog.text


def test_malformed_json_returns_non_zero(monkeypatch, caplog):
    class BadJsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{not-json"

    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: BadJsonResponse())
    client = HttpAgentApiClient("http://agent-api")

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_LIST_FAILED
    assert "resume_generation.list_failed" in caplog.text
    assert "agent_api_invalid_json" in caplog.text


def test_http_error_is_converted_to_safe_worker_error(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPError(
            "http://agent-api/resume-generation-requests",
            502,
            "Bad Gateway",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(worker, "urlopen", fail)
    client = HttpAgentApiClient("http://agent-api")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.list_requests()

    assert exc.value.reason == "agent_api_http_502"


@pytest.mark.parametrize(
    ("method_name", "record_id", "expected_reason"),
    [
        ("get_job", JOB_ID, "job_not_found"),
        ("get_resume", RESUME_ID, "source_resume_not_found"),
    ],
)
def test_record_404_is_converted_to_safe_worker_error(
    method_name,
    record_id,
    expected_reason,
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise HTTPError(
            "http://agent-api/redacted",
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(worker, "urlopen", fail)
    client = HttpAgentApiClient("http://agent-api")

    with pytest.raises(WorkerRuntimeError) as exc:
        getattr(client, method_name)(record_id)

    assert exc.value.reason == expected_reason


@pytest.mark.parametrize(
    ("raised", "expected_reason"),
    [
        (TimeoutError(), "agent_api_timeout"),
        (socket.timeout(), "agent_api_timeout"),
        (URLError("network down"), "agent_api_connection_error"),
    ],
)
def test_transport_errors_are_classified_safely(
    raised,
    expected_reason,
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise raised

    monkeypatch.setattr(worker, "urlopen", fail)
    client = HttpAgentApiClient("http://agent-api")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.list_requests()

    assert exc.value.reason == expected_reason


def test_generic_claim_failure_returns_claim_error_exit_code(caplog):
    client = FakeClient(
        [queued_request()],
        claim_error=WorkerRuntimeError("agent_api_connection_error"),
    )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_CLAIM_FAILED
    assert client.completed == []
    assert client.failed == []
    assert "resume_generation.claim_failed" in caplog.text
    assert REQUEST_ID in caplog.text


@pytest.mark.parametrize(
    "claim_response",
    [
        [CLAIM_TOKEN],
        {
            "id": REQUEST_ID,
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
        },
        {
            "id": REQUEST_ID,
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "claim_token": "   ",
        },
        {
            "id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "claim_token": CLAIM_TOKEN,
        },
    ],
    ids=["not-dictionary", "missing-token", "blank-token", "mismatched-id"],
)
def test_malformed_claim_response_stops_before_downstream_calls(
    claim_response,
    monkeypatch,
    caplog,
):
    client = FakeClient([queued_request()])
    monkeypatch.setattr(
        client,
        "claim_request",
        lambda request_id, worker_id: claim_response,
    )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_CLAIM_FAILED
    assert client.loaded_jobs == []
    assert client.loaded_resumes == []
    assert client.completed == []
    assert client.failed == []
    assert '"error": "malformed_claim_response"' in caplog.text
    assert "resume_generation.claim_failed" in caplog.text
    assert CLAIM_TOKEN not in caplog.text


def test_complete_failure_returns_non_zero(caplog):
    client = FakeClient(
        [queued_request()],
        complete_error=WorkerRuntimeError("agent_api_http_502"),
    )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_COMPLETE_FAILED
    assert client.completed == [(REQUEST_ID, CLAIM_TOKEN)]
    assert client.failed == []
    assert "resume_generation.complete_failed" in caplog.text


def test_placeholder_failure_calls_fail():
    client = FakeClient([queued_request()])

    def fail_generation(request):
        raise RuntimeError("placeholder failed")

    exit_code = run_once(client, worker_id="worker-a", generator=fail_generation)

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.completed == []
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "generation_failed")]


def test_fail_request_double_failure_preserves_safe_original_context(caplog):
    client = FakeClient(
        [queued_request()],
        fail_error=WorkerRuntimeError("agent_api_connection_error"),
    )

    def fail_generation(request):
        raise RuntimeError("placeholder failed")

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a", generator=fail_generation)

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "generation_failed")]
    assert "resume_generation.fail_request_failed" in caplog.text
    assert "generation_failed" in caplog.text
    assert "agent_api_connection_error" in caplog.text


def test_sensitive_exception_text_is_redacted(caplog):
    client = FakeClient([queued_request()])

    def fail_generation(request):
        raise RuntimeError(
            f"password=REDACT_ME profile content claim_token={CLAIM_TOKEN}"
        )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a", generator=fail_generation)

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "generation_failed")]
    assert "REDACT_ME" not in caplog.text
    assert "profile content" not in caplog.text
    assert CLAIM_TOKEN not in caplog.text


def test_missing_legacy_resume_id_fails_with_claim_token_unchanged(monkeypatch):
    client = FakeClient([queued_request()])
    original_claim = client.claim_request

    def claim_without_resume_id(request_id, worker_id):
        claimed = original_claim(request_id, worker_id)
        claimed.pop("resume_id")
        return claimed

    monkeypatch.setattr(client, "claim_request", claim_without_resume_id)

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.loaded_jobs == []
    assert client.loaded_resumes == []
    assert client.failed == [
        (REQUEST_ID, CLAIM_TOKEN, "source_resume_id_missing")
    ]


def test_missing_claimed_job_id_fails_safely(monkeypatch):
    client = FakeClient([queued_request()])
    original_claim = client.claim_request

    def claim_without_job_id(request_id, worker_id):
        claimed = original_claim(request_id, worker_id)
        claimed.pop("job_id")
        return claimed

    monkeypatch.setattr(client, "claim_request", claim_without_job_id)

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.loaded_jobs == []
    assert client.loaded_resumes == []
    assert client.failed == [
        (REQUEST_ID, CLAIM_TOKEN, "malformed_claim_response")
    ]


@pytest.mark.parametrize(
    ("client_kwargs", "expected_reason"),
    [
        (
            {"job_error": WorkerRuntimeError("job_not_found")},
            "job_not_found",
        ),
        (
            {"resume_error": WorkerRuntimeError("source_resume_not_found")},
            "source_resume_not_found",
        ),
        (
            {"job": {"title": "Platform Engineer"}},
            "malformed_job_response",
        ),
        (
            {"resume": {"id": RESUME_ID}},
            "malformed_resume_response",
        ),
    ],
)
def test_input_loading_failures_are_safe(client_kwargs, expected_reason):
    client = FakeClient([queued_request()], **client_kwargs)

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.completed == []
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, expected_reason)]


def test_input_loading_never_logs_sensitive_records(caplog):
    job_secret = "JOB_DESCRIPTION_MUST_NOT_LEAK"
    resume_secret = "RESUME_CONTENT_MUST_NOT_LEAK"
    client = FakeClient(
        [queued_request()],
        job={**job_record(), "description": job_secret},
        resume={**resume_record(), "content": resume_secret},
    )

    def fail_generation(generation_input):
        raise RuntimeError(
            f"{generation_input.job_description} "
            f"{generation_input.source_resume_content}"
        )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(
            client,
            worker_id="worker-a",
            generator=fail_generation,
        )

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "generation_failed")]
    assert job_secret not in caplog.text
    assert resume_secret not in caplog.text


def test_claim_token_never_appears_in_logs(caplog):
    client = FakeClient(
        [queued_request()],
        complete_error=RuntimeError(f"upstream leaked {CLAIM_TOKEN}"),
    )

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        run_once(client, worker_id="worker-a")

    assert CLAIM_TOKEN not in caplog.text


def test_http_llm_client_returns_valid_structured_result(monkeypatch):
    captured = []
    response_body = json.dumps(
        gateway_envelope(
            provider="configured-provider",
            model="configured-model",
        )
    ).encode()

    def respond(request, timeout):
        captured.append((request, timeout))
        return HttpResponse(response_body)

    monkeypatch.setattr(worker, "urlopen", respond)
    client = HttpLlmGatewayClient(
        "http://internal-gateway",
        provider="configured-provider",
        model="configured-model",
        temperature=0.3,
        max_output_tokens=2048,
        timeout_seconds=12,
    )

    result = client.generate(generation_request())

    assert result == ResumeGenerationResult(**valid_generation_output())
    request, timeout = captured[0]
    assert request.full_url == "http://internal-gateway/generate"
    assert timeout == 12
    payload = json.loads(request.data)
    assert payload == {
        "request_id": REQUEST_ID,
        "task_type": "resume_generation",
        "prompt_template": worker.TRUTHFUL_RESUME_INSTRUCTIONS,
        "variables": {
            "request_id": REQUEST_ID,
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "job_title": "Platform Engineer",
            "company": "Example Corp",
            "job_description": "Build reliable systems",
            "required_skills": ["Python", "PostgreSQL"],
            "preferred_skills": ["Kubernetes"],
            "source_resume_content": "Experienced platform engineer",
        },
        "provider": "configured-provider",
        "model": "configured-model",
        "temperature": 0.3,
        "max_output_tokens": 2048,
        "metadata": {"job_id": JOB_ID, "resume_id": RESUME_ID},
    }
    instructions = payload["prompt_template"].lower()
    for required_instruction in (
        "use only facts present in the source resume",
        "do not invent employers",
        "do not invent projects",
        "do not invent certifications",
        "do not invent education",
        "do not inflate years of experience",
        "preserve truthful dates and technologies",
        "report unsupported claims",
    ):
        assert required_instruction in instructions


@pytest.mark.parametrize(
    "output",
    [
        [],
        valid_generation_output(extra="not allowed"),
        valid_generation_output(change_summary=[1]),
        valid_generation_output(tailored_resume_content="   "),
    ],
)
def test_http_llm_client_rejects_malformed_response(output, monkeypatch):
    body = json.dumps(gateway_envelope(json.dumps(output))).encode()
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpResponse(body))
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "llm_gateway_malformed_response"


def test_http_llm_client_rejects_invalid_outer_json(monkeypatch):
    monkeypatch.setattr(
        worker,
        "urlopen",
        lambda *args, **kwargs: HttpResponse(b"not-json"),
    )
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "llm_gateway_invalid_json"


@pytest.mark.parametrize(
    "output_text",
    [
        "not-json",
        "```json\n{}\n```",
        '{"tailored_resume_content": "valid"} surrounding prose',
    ],
    ids=["invalid-json", "markdown-fence", "surrounding-prose"],
)
def test_http_llm_client_rejects_non_object_output_text(
    output_text,
    monkeypatch,
):
    body = json.dumps(gateway_envelope(output_text)).encode()
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpResponse(body))
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "llm_gateway_malformed_response"


@pytest.mark.parametrize(
    "envelope",
    [
        {key: value for key, value in gateway_envelope().items() if key != "latency_ms"},
        gateway_envelope(extra="not allowed"),
        gateway_envelope(input_tokens=-1),
        gateway_envelope(redactions_applied=[1]),
    ],
    ids=["missing-field", "extra-field", "negative-token", "bad-redactions"],
)
def test_http_llm_client_rejects_malformed_outer_envelope(envelope, monkeypatch):
    body = json.dumps(envelope).encode()
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpResponse(body))
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "llm_gateway_malformed_response"


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"},
        {"provider": "other-provider"},
        {"model": "other-model"},
    ],
    ids=["request-id", "provider", "model"],
)
def test_http_llm_client_rejects_envelope_identity_mismatch(
    overrides,
    monkeypatch,
):
    body = json.dumps(gateway_envelope(**overrides)).encode()
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpResponse(body))
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "llm_gateway_malformed_response"


def test_http_llm_client_fails_closed_on_unsupported_claims(monkeypatch):
    output = valid_generation_output(unsupported_claims=["Invented certification"])
    body = json.dumps(gateway_envelope(json.dumps(output))).encode()
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpResponse(body))
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == "resume_generation_unsupported_claims"


@pytest.mark.parametrize(
    ("raised", "expected_reason"),
    [
        (TimeoutError("private timeout details"), "llm_gateway_timeout"),
        (URLError("private connection details"), "llm_gateway_connection_error"),
    ],
)
def test_http_llm_client_sanitizes_transport_failures(
    raised,
    expected_reason,
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise raised

    monkeypatch.setattr(worker, "urlopen", fail)
    client = HttpLlmGatewayClient("http://gateway", "provider", "model")

    with pytest.raises(WorkerRuntimeError) as exc:
        client.generate(generation_request())

    assert exc.value.reason == expected_reason


@pytest.mark.parametrize(
    ("result", "error", "reason"),
    [
        (None, WorkerRuntimeError("llm_gateway_malformed_response"), "llm_gateway_malformed_response"),
        (
            ResumeGenerationResult(
                **valid_generation_output(unsupported_claims=["Invented employer"])
            ),
            None,
            "resume_generation_unsupported_claims",
        ),
    ],
)
def test_invalid_generation_never_completes(result, error, reason):
    client = FakeClient([queued_request()])
    llm_client = FakeLlmClient(result=result, error=error)

    exit_code = run_once(client, worker_id="worker-a", llm_client=llm_client)

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.completed == []
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, reason)]


def test_valid_generation_result_reaches_completion():
    client = FakeClient([queued_request()])
    llm_client = FakeLlmClient()

    exit_code = run_once(client, worker_id="worker-a", llm_client=llm_client)

    assert exit_code == EXIT_SUCCESS
    assert llm_client.requests == [generation_request()]
    assert client.completed == [(REQUEST_ID, CLAIM_TOKEN)]
    assert client.failed == []


def test_gateway_sensitive_content_is_absent_from_logs(caplog):
    sensitive = "PRIVATE_RESUME_AND_GENERATED_CONTENT"
    client = FakeClient(
        [queued_request()],
        job={**job_record(), "description": sensitive},
        resume={**resume_record(), "content": sensitive},
    )
    llm_client = FakeLlmClient(error=RuntimeError(sensitive))

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(
            client,
            worker_id="worker-a",
            llm_client=llm_client,
        )

    assert exit_code == EXIT_GENERATION_FAILED
    assert sensitive not in caplog.text
    assert CLAIM_TOKEN not in caplog.text
