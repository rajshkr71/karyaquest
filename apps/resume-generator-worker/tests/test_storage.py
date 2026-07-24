from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_generator_worker import worker
from resume_generator_worker.storage import (
    ArtifactMetadata,
    ArtifactStat,
    ArtifactStorageError,
    MinioArtifactStore,
    canonical_artifact_bytes,
    persist_artifact,
    validate_storage_configuration,
)
from resume_generator_worker.worker import (
    EXIT_COMPLETE_FAILED,
    EXIT_GENERATION_FAILED,
    EXIT_SUCCESS,
    HttpAgentApiClient,
    LlmGenerationExecution,
    ResumeGenerationRequest,
    ResumeGenerationResult,
    WorkerRuntimeError,
    artifact_metadata_matches,
    parse_minio_secure,
    run_once,
)

REQUEST_ID = "2ecee968-87dc-43bf-bf6b-10b5c4cfd379"
JOB_ID = "e56ee8f6-9e6d-4d12-b826-bf69f4d545bf"
RESUME_ID = "fb936cab-0161-4780-b69d-bf6bc76a0119"
CLAIM_TOKEN = "78cd0b26-b30a-4cf6-8c1e-031a0036fc45"
ARTIFACT_ID = "4b3f3c46-6549-4c50-92c6-2f57aee36b36"


def generation_request(content="Source résumé facts"):
    return ResumeGenerationRequest(
        request_id=REQUEST_ID,
        job_id=JOB_ID,
        resume_id=RESUME_ID,
        job_title="Engineer",
        company="Example",
        job_description="Private job description",
        required_skills=["Python"],
        preferred_skills=["Kubernetes"],
        source_resume_content=content,
    )


def generation_result(content="Tailored résumé — truthful"):
    return ResumeGenerationResult(
        tailored_resume_content=content,
        change_summary=["Reordered skills"],
        source_facts_used=["Python"],
        unsupported_claims=[],
    )


def execution(result=None):
    return LlmGenerationExecution(
        result=result or generation_result(),
        provider="provider",
        model="model",
        model_version="model-v1",
        input_tokens=10,
        output_tokens=20,
        latency_ms=30,
        finish_reason="stop",
    )


class FakeStore:
    def __init__(
        self,
        stat_result=None,
        stat_error=None,
        upload_error=None,
        create_result=True,
        events=None,
    ):
        self.stat_result = stat_result
        self.stat_error = stat_error
        self.upload_error = upload_error
        self.create_result = create_result
        self.events = events if events is not None else []
        self.create_calls = []
        self.uploads = []
        self.removals = []

    def stat(self, bucket, key):
        self.events.append("stat")
        if self.stat_error:
            raise self.stat_error
        return self.stat_result

    def create_only(self, bucket, key, content, content_type, metadata):
        self.events.append("upload")
        if self.upload_error:
            raise self.upload_error
        call = (bucket, key, content, content_type, metadata)
        self.create_calls.append(call)
        if self.create_result:
            self.uploads.append(call)
        if self.stat_result is None and self.create_result:
            self.stat_result = ArtifactStat(
                hashlib.sha256(content).hexdigest(), len(content)
            )
        return self.create_result

    def remove(self, bucket, key):
        self.events.append("remove")
        self.removals.append((bucket, key))


class FakeAgentApi:
    def __init__(self, complete_error=None, artifact=None, artifact_error=None, events=None):
        self.complete_error = complete_error
        self.artifact = artifact
        self.artifact_error = artifact_error
        self.events = events if events is not None else []
        self.completed = []
        self.failed = []

    def list_requests(self):
        return [{"id": REQUEST_ID, "status": "queued"}]

    def claim_request(self, request_id, worker_id):
        return {
            "id": request_id,
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "status": "processing",
            "claim_token": CLAIM_TOKEN,
        }

    def get_job(self, job_id):
        return {
            "id": JOB_ID,
            "title": "Engineer",
            "company": "Example",
            "description": "Private job description",
            "required_skills": ["Python"],
            "preferred_skills": ["Kubernetes"],
        }

    def get_resume(self, resume_id):
        return {"id": RESUME_ID, "content": "Source résumé facts"}

    def complete_request(self, request_id, claim_token, artifact):
        self.events.append("complete")
        self.completed.append((request_id, claim_token, artifact))
        if self.complete_error:
            raise self.complete_error
        return {"id": request_id, "status": "completed"}

    def get_artifact(self, request_id, job_id, source_resume_id):
        self.events.append("get-artifact")
        if self.artifact_error:
            raise self.artifact_error
        return self.artifact

    def fail_request(self, request_id, claim_token, failure_reason):
        self.events.append("fail")
        self.failed.append((request_id, claim_token, failure_reason))
        return {"id": request_id, "status": "failed"}


class FakeLlm:
    def __init__(self, value=None):
        self.value = value or execution()

    def generate(self, request):
        return self.value


def expected_metadata():
    content = canonical_artifact_bytes(generation_request(), generation_result())
    return ArtifactMetadata(
        storage_bucket="generated-documents",
        storage_key=f"resume-generation/{REQUEST_ID}/result.json",
        content_type="application/json",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        provider="provider",
        model="model",
        model_version="model-v1",
        input_tokens=10,
        output_tokens=20,
        latency_ms=30,
        finish_reason="stop",
    )


def artifact_response(**overrides):
    return {
        "id": ARTIFACT_ID,
        "request_id": REQUEST_ID,
        "job_id": JOB_ID,
        "source_resume_id": RESUME_ID,
        **asdict(expected_metadata()),
        "created_at": "2026-07-24T12:00:00Z",
    } | overrides


def test_canonical_serialization_is_deterministic_unicode_and_minimal():
    first = canonical_artifact_bytes(generation_request(), generation_result())
    second = canonical_artifact_bytes(generation_request(), generation_result())
    decoded = json.loads(first)

    assert first == second
    assert "résumé" in first.decode("utf-8")
    assert decoded == {
        "schema_version": 1,
        "request_id": REQUEST_ID,
        "job_id": JOB_ID,
        "source_resume_id": RESUME_ID,
        **asdict(generation_result()),
    }
    assert "Source résumé facts" not in first.decode()
    assert "Private job description" not in first.decode()


def test_new_artifact_upload_has_checksum_size_key_and_safe_metadata():
    store = FakeStore()

    stored = persist_artifact(
        store, generation_request(), execution(), "generated-documents"
    )

    assert stored.created is True
    assert stored.metadata == expected_metadata()
    bucket, key, content, content_type, metadata = store.uploads[0]
    assert (bucket, key, content_type) == (
        "generated-documents",
        f"resume-generation/{REQUEST_ID}/result.json",
        "application/json",
    )
    assert stored.metadata.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.metadata.size_bytes == len(content)
    assert metadata == {
        "sha256": stored.metadata.sha256,
        "request-id": REQUEST_ID,
        "job-id": JOB_ID,
        "source-resume-id": RESUME_ID,
    }


def test_identical_existing_artifact_is_reused_without_upload():
    metadata = expected_metadata()
    store = FakeStore(
        ArtifactStat(metadata.sha256, metadata.size_bytes), create_result=False
    )

    stored = persist_artifact(
        store, generation_request(), execution(), "generated-documents"
    )

    assert stored.created is False
    assert store.uploads == []


@pytest.mark.parametrize(
    "stat",
    [ArtifactStat("0" * 64, 1), ArtifactStat(expected_metadata().sha256, 1)],
)
def test_mismatched_existing_artifact_fails_closed(stat):
    with pytest.raises(ArtifactStorageError) as exc:
        persist_artifact(
            FakeStore(stat, create_result=False), generation_request(), execution(), "generated-documents"
        )
    assert exc.value.reason == "artifact_storage_conflict"


@pytest.mark.parametrize(
    "reason",
    ["artifact_storage_connection_error", "artifact_storage_timeout"],
)
def test_storage_failure_invokes_fail_without_completion(reason):
    client = FakeAgentApi()
    store = FakeStore(stat_error=ArtifactStorageError(reason))

    exit_code = run_once(
        client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
    )

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.completed == []
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, reason)]


def test_upload_failure_invokes_fail_endpoint():
    client = FakeAgentApi()
    store = FakeStore(
        upload_error=ArtifactStorageError("artifact_storage_connection_error")
    )

    exit_code = run_once(
        client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
    )

    assert exit_code == EXIT_GENERATION_FAILED
    assert client.completed == []
    assert client.failed == [
        (REQUEST_ID, CLAIM_TOKEN, "artifact_storage_connection_error")
    ]


def test_success_uploads_before_exact_completion_body():
    events = []
    client = FakeAgentApi(events=events)
    store = FakeStore(events=events)

    exit_code = run_once(
        client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
    )

    assert exit_code == EXIT_SUCCESS
    assert events.index("upload") < events.index("complete")
    assert client.completed == [(REQUEST_ID, CLAIM_TOKEN, expected_metadata())]


def test_http_completion_body_has_exact_shape(monkeypatch):
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    def respond(request, timeout):
        captured.append(request)
        return Response()

    monkeypatch.setattr(worker, "urlopen", respond)
    HttpAgentApiClient("http://agent-api").complete_request(
        REQUEST_ID, CLAIM_TOKEN, expected_metadata()
    )

    assert json.loads(captured[0].data) == {
        "claim_token": CLAIM_TOKEN,
        "artifact": asdict(expected_metadata()),
    }
    assert "request_id" not in json.loads(captured[0].data)["artifact"]


@pytest.mark.parametrize(
    "complete_error",
    [
        WorkerRuntimeError("agent_api_timeout"),
        WorkerRuntimeError("agent_api_http_409"),
    ],
)
def test_matching_reconciliation_is_success(complete_error):
    client = FakeAgentApi(
        complete_error=complete_error,
        artifact=artifact_response(),
    )
    exit_code = run_once(
        client, worker_id="w", llm_client=FakeLlm(), artifact_store=FakeStore()
    )
    assert exit_code == EXIT_SUCCESS
    assert client.failed == []
    assert len(client.completed) == 1


def test_uncertain_completion_never_deletes_and_logs_manual_action(caplog):
    store = FakeStore()
    client = FakeAgentApi(
        complete_error=WorkerRuntimeError("agent_api_timeout"),
        artifact_error=WorkerRuntimeError("agent_api_connection_error"),
    )
    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(
            client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
        )
    assert exit_code == EXIT_COMPLETE_FAILED
    assert store.removals == []
    assert "resume_generation.manual_action_required" in caplog.text


@pytest.mark.parametrize("reused", [False, True])
def test_definitive_rejection_deletes_only_new_object(reused):
    metadata = expected_metadata()
    stat = ArtifactStat(metadata.sha256, metadata.size_bytes) if reused else None
    store = FakeStore(stat, create_result=not reused)
    client = FakeAgentApi(complete_error=WorkerRuntimeError("agent_api_http_422"))

    exit_code = run_once(
        client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
    )

    assert exit_code == EXIT_COMPLETE_FAILED
    assert bool(store.removals) is (not reused)
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "agent_api_http_422")]


def test_unsupported_claims_never_upload():
    bad = ResumeGenerationResult(
        **(asdict(generation_result()) | {"unsupported_claims": ["invented"]})
    )
    store = FakeStore()
    client = FakeAgentApi()

    exit_code = run_once(
        client,
        worker_id="w",
        llm_client=FakeLlm(execution(bad)),
        artifact_store=store,
    )

    assert exit_code == EXIT_GENERATION_FAILED
    assert store.events == []
    assert client.failed[-1][2] == "resume_generation_unsupported_claims"


def test_sensitive_values_never_appear_in_logs(caplog):
    access_key = "ACCESS_KEY_MUST_NOT_LEAK"
    secret_key = "SECRET_KEY_MUST_NOT_LEAK"
    store = FakeStore(
        stat_error=ArtifactStorageError("artifact_storage_connection_error")
    )
    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        run_once(
            FakeAgentApi(),
            worker_id="w",
            llm_client=FakeLlm(),
            artifact_store=store,
        )
    for sensitive in (
        "Tailored résumé — truthful",
        "Source résumé facts",
        "Private job description",
        CLAIM_TOKEN,
        access_key,
        secret_key,
    ):
        assert sensitive not in caplog.text


def test_main_requires_storage_credentials_without_network(monkeypatch, caplog):
    for name in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        assert worker.main() == EXIT_GENERATION_FAILED
    assert "artifact_storage_configuration_error" in caplog.text


class FakeMinioClient:
    def __init__(self, *, stat_response=None, execute_error=None, stat_error=None):
        self.stat_response = stat_response
        self.execute_error = execute_error
        self.stat_error = stat_error
        self.execute_calls = []
        self.stat_calls = []
        self.remove_calls = []

    def _execute(self, *args, **kwargs):
        self.execute_calls.append((args, kwargs))
        if self.execute_error:
            raise self.execute_error

    def stat_object(self, bucket, key):
        self.stat_calls.append((bucket, key))
        if self.stat_error:
            raise self.stat_error
        return self.stat_response

    def remove_object(self, bucket, key):
        self.remove_calls.append((bucket, key))


def minio_store(client):
    store = MinioArtifactStore.__new__(MinioArtifactStore)
    store.client = client
    return store


@pytest.mark.parametrize("key", ["sha256", "X-Amz-Meta-Sha256", "x-amz-meta-sha256"])
def test_minio_stat_accepts_case_insensitive_checksum_metadata(key):
    metadata = expected_metadata()
    client = FakeMinioClient(
        stat_response=SimpleNamespace(
            metadata={key: metadata.sha256}, size=metadata.size_bytes
        )
    )
    assert minio_store(client).stat("bucket", "key") == ArtifactStat(
        metadata.sha256, metadata.size_bytes
    )


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(metadata={}, size=1),
        SimpleNamespace(metadata={"sha256": "x" * 64}, size=1),
        SimpleNamespace(metadata={"sha256": "0" * 64}, size=None),
        SimpleNamespace(metadata={"sha256": "0" * 64}, size="1"),
    ],
)
def test_minio_stat_rejects_missing_or_malformed_metadata(response):
    with pytest.raises(ArtifactStorageError) as exc:
        minio_store(FakeMinioClient(stat_response=response)).stat("bucket", "key")
    assert exc.value.reason == "artifact_storage_invalid_response"


def test_minio_conditional_create_uses_signed_sdk_path_and_exact_headers():
    client = FakeMinioClient()
    content = "résumé".encode("utf-8")
    assert minio_store(client).create_only(
        "bucket", "request/result.json", content, "application/json", {"sha256": "0" * 64}
    ) is True
    args, kwargs = client.execute_calls[0]
    assert args == ("PUT", "bucket", "request/result.json")
    assert kwargs["headers"]["If-None-Match"] == "*"
    assert kwargs["headers"]["Content-Length"] == str(len(content))
    assert kwargs["headers"]["X-Amz-Meta-sha256"] == "0" * 64
    assert client.execute_calls and not hasattr(client, "put_object_calls")


def test_precondition_race_stats_and_reuses_without_overwrite():
    class PreconditionFailed(Exception):
        code = "PreconditionFailed"
        status = 412

    metadata = expected_metadata()
    client = FakeMinioClient(
        execute_error=PreconditionFailed(),
        stat_response=SimpleNamespace(
            metadata={"X-Amz-Meta-Sha256": metadata.sha256},
            size=metadata.size_bytes,
        ),
    )
    stored = persist_artifact(
        minio_store(client), generation_request(), execution(), "generated-documents"
    )
    assert stored.created is False
    assert len(client.execute_calls) == 1
    assert client.stat_calls == [(metadata.storage_bucket, metadata.storage_key)]


def test_precondition_race_with_mismatch_conflicts_without_overwrite():
    class PreconditionFailed(Exception):
        code = "PreconditionFailed"

    client = FakeMinioClient(
        execute_error=PreconditionFailed(),
        stat_response=SimpleNamespace(metadata={"sha256": "0" * 64}, size=1),
    )
    with pytest.raises(ArtifactStorageError) as exc:
        persist_artifact(
            minio_store(client), generation_request(), execution(), "generated-documents"
        )
    assert exc.value.reason == "artifact_storage_conflict"
    assert len(client.execute_calls) == 1


def test_minio_remove_targets_exact_bucket_and_key():
    client = FakeMinioClient()
    minio_store(client).remove("generated-documents", "resume-generation/id/result.json")
    assert client.remove_calls == [
        ("generated-documents", "resume-generation/id/result.json")
    ]


@pytest.mark.parametrize("value, expected", [(" true ", True), ("FALSE", False)])
def test_parse_minio_secure_accepts_only_boolean_words(value, expected):
    assert parse_minio_secure(value) is expected


@pytest.mark.parametrize("value", ["", " ", "1", "0", "yes", "no", "tru"])
def test_parse_minio_secure_rejects_ambiguous_values(value):
    with pytest.raises(ArtifactStorageError) as exc:
        parse_minio_secure(value)
    assert exc.value.reason == "artifact_storage_configuration_error"


@pytest.mark.parametrize(
    "values",
    [
        (" ", "access", "secret", "generated-documents"),
        ("minio:9000", " ", "secret", "generated-documents"),
        ("minio:9000", "access", " ", "generated-documents"),
        ("minio:9000", "access", "secret", "Bad_Bucket"),
    ],
)
def test_storage_configuration_rejects_invalid_values(values):
    with pytest.raises(ArtifactStorageError) as exc:
        validate_storage_configuration(*values)
    assert exc.value.reason == "artifact_storage_configuration_error"


@pytest.mark.parametrize("bad_value", [True, 1.0, "1"])
def test_artifact_comparison_rejects_non_integer_metric_types(bad_value):
    actual = artifact_response(size_bytes=bad_value)
    assert not artifact_metadata_matches(
        actual, expected_metadata(), REQUEST_ID, JOB_ID, RESUME_ID
    )


def test_artifact_comparison_rejects_extra_fields_and_identifier_mismatch():
    assert not artifact_metadata_matches(
        artifact_response(extra="value"), expected_metadata(), REQUEST_ID, JOB_ID, RESUME_ID
    )
    assert not artifact_metadata_matches(
        artifact_response(job_id=REQUEST_ID), expected_metadata(), REQUEST_ID, JOB_ID, RESUME_ID
    )


class HttpJsonResponse:
    def __init__(self, value):
        self.body = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


def test_http_get_artifact_valid_response(monkeypatch):
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpJsonResponse(artifact_response()))
    assert HttpAgentApiClient("http://agent-api").get_artifact(
        REQUEST_ID, JOB_ID, RESUME_ID
    ) == artifact_response()


def test_http_get_artifact_404_is_distinct(monkeypatch):
    def not_found(*args, **kwargs):
        raise HTTPError("http://agent-api/artifact", 404, "Not Found", None, None)

    monkeypatch.setattr(worker, "urlopen", not_found)
    assert HttpAgentApiClient("http://agent-api").get_artifact(
        REQUEST_ID, JOB_ID, RESUME_ID
    ) is None


@pytest.mark.parametrize(
    "raised, reason",
    [
        (TimeoutError(), "agent_api_timeout"),
        (URLError("offline"), "agent_api_connection_error"),
    ],
)
def test_http_get_artifact_transport_errors(monkeypatch, raised, reason):
    def fail(*args, **kwargs):
        raise raised

    monkeypatch.setattr(worker, "urlopen", fail)
    with pytest.raises(WorkerRuntimeError) as exc:
        HttpAgentApiClient("http://agent-api").get_artifact(
            REQUEST_ID, JOB_ID, RESUME_ID
        )
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    "response",
    [
        b"{bad-json",
        [],
        {"request_id": REQUEST_ID},
        artifact_response(extra="unexpected"),
        artifact_response(size_bytes=True),
        artifact_response(input_tokens="10"),
    ],
)
def test_http_get_artifact_rejects_invalid_response(monkeypatch, response):
    monkeypatch.setattr(worker, "urlopen", lambda *args, **kwargs: HttpJsonResponse(response))
    with pytest.raises(WorkerRuntimeError) as exc:
        HttpAgentApiClient("http://agent-api").get_artifact(
            REQUEST_ID, JOB_ID, RESUME_ID
        )
    assert exc.value.reason == "agent_api_invalid_json"


@pytest.mark.parametrize(
    "complete_reason, artifact, should_remove",
    [
        ("agent_api_timeout", None, False),
        ("agent_api_connection_error", None, False),
        ("agent_api_http_409", None, True),
        ("agent_api_http_409", {"request_id": REQUEST_ID}, False),
    ],
)
def test_reconciliation_404_and_malformed_cleanup_rules(
    complete_reason, artifact, should_remove, caplog
):
    store = FakeStore()
    client = FakeAgentApi(
        complete_error=WorkerRuntimeError(complete_reason), artifact=artifact
    )
    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(
            client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
        )
    assert exit_code == EXIT_COMPLETE_FAILED
    assert len(client.completed) == 1
    assert bool(store.removals) is should_remove
    if not should_remove:
        assert "resume_generation.manual_action_required" in caplog.text


def test_unknown_storage_reason_is_allowlisted_before_failure_and_logging(caplog):
    store = FakeStore(upload_error=ArtifactStorageError("secret internal storage detail"))
    client = FakeAgentApi()
    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(
            client, worker_id="w", llm_client=FakeLlm(), artifact_store=store
        )
    assert exit_code == EXIT_GENERATION_FAILED
    assert client.failed[-1][2] == "artifact_storage_invalid_response"
    assert "secret internal storage detail" not in caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": " "},
        {"input_tokens": True},
        {"output_tokens": 1.5},
        {"latency_ms": -1},
    ],
)
def test_injected_execution_is_validated_before_upload(changes):
    bad_execution = LlmGenerationExecution(**(execution().__dict__ | changes))
    store = FakeStore()
    client = FakeAgentApi()
    exit_code = run_once(
        client,
        worker_id="w",
        llm_client=FakeLlm(bad_execution),
        artifact_store=store,
    )
    assert exit_code == EXIT_GENERATION_FAILED
    assert store.create_calls == []
    assert client.failed[-1][2] == "llm_gateway_malformed_response"
