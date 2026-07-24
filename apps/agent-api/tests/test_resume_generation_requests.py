from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent_api import db, resume_generation_requests
from agent_api.main import app

REQUEST_ID = UUID("2ecee968-87dc-43bf-bf6b-10b5c4cfd379")
APPROVAL_ID = UUID("6f5be64c-b698-4024-b5df-5a6b730e2807")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
RESUME_ID = UUID("fb936cab-0161-4780-b69d-bf6bc76a0119")
CLAIM_TOKEN = UUID("0059f9f3-428c-4eaf-94ba-dc3589756496")
ARTIFACT_ID = UUID("dc49d8d2-8077-4518-b85b-4488b84e481d")
SHA256 = "a" * 64
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def request_record(**overrides):
    record = {
        "id": REQUEST_ID,
        "job_id": JOB_ID,
        "approval_id": APPROVAL_ID,
        "resume_id": RESUME_ID,
        "status": "queued",
        "failure_reason": None,
        "processing_started_at": None,
        "completed_at": None,
        "failed_at": None,
        "worker_id": None,
        "claim_token": None,
        "attempt_count": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return record | overrides


def artifact_values(**overrides):
    values = {
        "storage_bucket": "generated-resumes",
        "storage_key": f"requests/{REQUEST_ID}/resume.md",
        "content_type": "text/markdown",
        "sha256": SHA256,
        "size_bytes": 1234,
        "provider": "configured-provider",
        "model": "configured-model",
        "model_version": "configured-model-v1",
        "input_tokens": 100,
        "output_tokens": 200,
        "latency_ms": 300,
        "finish_reason": "stop",
    }
    return values | overrides


def artifact_record(**overrides):
    return {
        "id": ARTIFACT_ID,
        "request_id": REQUEST_ID,
        "job_id": JOB_ID,
        "source_resume_id": RESUME_ID,
        **artifact_values(),
        "created_at": NOW,
    } | overrides


def completion_payload(**artifact_overrides):
    return resume_generation_requests.ResumeGenerationRequestCompletion(
        claim_token=CLAIM_TOKEN,
        artifact=resume_generation_requests.ResumeGenerationArtifactCreate(
            **artifact_values(**artifact_overrides),
        ),
    )


def test_create_resume_generation_request_route_returns_queued(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        lambda settings, job_id, resume_id: request_record(resume_id=resume_id),
    )

    result = resume_generation_requests.create_for_job(
        JOB_ID,
        resume_generation_requests.ResumeGenerationRequestCreate(
            resume_id=RESUME_ID,
        ),
        object(),
    )

    assert result["job_id"] == JOB_ID
    assert result["approval_id"] == APPROVAL_ID
    assert result["resume_id"] == RESUME_ID
    assert result["status"] == "queued"


def test_create_resume_generation_request_missing_job_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        lambda settings, job_id, resume_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(
            JOB_ID,
            resume_generation_requests.ResumeGenerationRequestCreate(
                resume_id=RESUME_ID,
            ),
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "job not found"


def test_create_resume_generation_request_missing_approval_returns_409(
    monkeypatch,
) -> None:
    def missing_approval(settings, job_id, resume_id):
        raise db.ResumeGenerationApprovalMissing

    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        missing_approval,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(
            JOB_ID,
            resume_generation_requests.ResumeGenerationRequestCreate(
                resume_id=RESUME_ID,
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "resume generation approval is required"


def test_create_resume_generation_request_duplicate_active_returns_409(
    monkeypatch,
) -> None:
    def duplicate(settings, job_id, resume_id):
        raise db.ActiveResumeGenerationRequestExists

    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        duplicate,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(
            JOB_ID,
            resume_generation_requests.ResumeGenerationRequestCreate(
                resume_id=RESUME_ID,
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "an active resume generation request already exists"


def test_create_resume_generation_request_missing_resume_returns_404(
    monkeypatch,
) -> None:
    def missing_resume(settings, job_id, resume_id):
        raise db.SourceResumeNotFound

    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        missing_resume,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(
            JOB_ID,
            resume_generation_requests.ResumeGenerationRequestCreate(
                resume_id=RESUME_ID,
            ),
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "source resume not found"


def test_create_payload_requires_resume_id() -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestCreate()


def test_list_resume_generation_requests(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "list_resume_generation_requests",
        lambda settings: [request_record()],
    )

    assert resume_generation_requests.list_all(object()) == [request_record()]


def test_list_response_model_omits_claim_token() -> None:
    response = resume_generation_requests.ResumeGenerationRequest.model_validate(
        request_record(claim_token=CLAIM_TOKEN),
    ).model_dump()

    assert "claim_token" not in response


def test_get_resume_generation_request(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "get_resume_generation_request",
        lambda settings, request_id: request_record(),
    )

    assert resume_generation_requests.get(REQUEST_ID, object()) == request_record()


def test_get_response_model_omits_claim_token() -> None:
    response = resume_generation_requests.ResumeGenerationRequest.model_validate(
        request_record(claim_token=CLAIM_TOKEN),
    ).model_dump()

    assert "claim_token" not in response


def test_get_resume_generation_request_missing_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "get_resume_generation_request",
        lambda settings, request_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.get(REQUEST_ID, object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "resume generation request not found"


def test_valid_completion_returns_artifact(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "complete_resume_generation_request",
        lambda settings, request_id, claim_token, artifact: request_record(
            status="completed",
            processing_started_at=NOW,
            completed_at=NOW,
        )
        | {"artifact": artifact_record()},
    )

    result = resume_generation_requests.complete(
        REQUEST_ID, completion_payload(), object()
    )

    assert result["status"] == "completed"
    assert result["artifact"] == artifact_record()


def test_claim_transition_requires_worker_and_persists_claim_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None, worker_id=None, claim_token=None: request_record(
            status=status,
            worker_id=worker_id,
            claim_token=CLAIM_TOKEN,
            attempt_count=1,
            processing_started_at=NOW,
        ),
    )

    result = resume_generation_requests.claim(
        REQUEST_ID,
        resume_generation_requests.ResumeGenerationRequestClaim(
            worker_id=" worker-a ",
        ),
        object(),
    )

    assert result["status"] == "processing"
    assert result["worker_id"] == "worker-a"
    assert result["claim_token"] == CLAIM_TOKEN
    assert result["attempt_count"] == 1


def test_claim_response_model_includes_claim_token() -> None:
    response = resume_generation_requests.ResumeGenerationRequestClaimed.model_validate(
        request_record(
            status="processing",
            worker_id="worker-a",
            claim_token=CLAIM_TOKEN,
            attempt_count=1,
            processing_started_at=NOW,
        ),
    ).model_dump()

    assert response["claim_token"] == CLAIM_TOKEN
    assert response["resume_id"] == RESUME_ID


def test_blank_worker_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestClaim(worker_id="   ")


def test_duplicate_claim_returns_409_with_valid_worker_id(monkeypatch) -> None:
    def already_claimed(
        settings,
        request_id,
        status,
        failure_reason=None,
        worker_id=None,
        claim_token=None,
    ):
        assert worker_id == "worker-b"
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        already_claimed,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.claim(
            REQUEST_ID,
            resume_generation_requests.ResumeGenerationRequestClaim(
                worker_id="worker-b",
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_start_endpoint_is_not_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/resume-generation-requests/{request_id}/start" not in paths
    assert "/resume-generation-requests/{request_id}/claim" in paths


def test_valid_failed_transition(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None, worker_id=None, claim_token=None: request_record(
            status=status,
            failure_reason=failure_reason,
            failed_at=NOW,
            processing_started_at=NOW,
        ),
    )

    result = resume_generation_requests.fail(
        REQUEST_ID,
        resume_generation_requests.ResumeGenerationRequestFailure(
            claim_token=CLAIM_TOKEN,
            failure_reason=" upstream failed ",
        ),
        object(),
    )

    assert result["status"] == "failed"
    assert result["failure_reason"] == "upstream failed"


def test_invalid_completion_transition_returns_409(monkeypatch) -> None:
    def invalid(settings, request_id, claim_token, artifact):
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "complete_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.complete(REQUEST_ID, completion_payload(), object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_invalid_failure_transition_returns_409(monkeypatch) -> None:
    def invalid(
        settings,
        request_id,
        status,
        failure_reason=None,
        worker_id=None,
        claim_token=None,
    ):
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.fail(
            REQUEST_ID,
            resume_generation_requests.ResumeGenerationRequestFailure(
                claim_token=CLAIM_TOKEN,
                failure_reason="boom",
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_complete_requires_correct_claim_token(monkeypatch) -> None:
    def complete_request(settings, request_id, claim_token, artifact):
        assert claim_token == CLAIM_TOKEN
        return request_record(
            status="completed",
            processing_started_at=NOW,
            completed_at=NOW,
            worker_id="worker-a",
            attempt_count=1,
        ) | {"artifact": artifact_record()}

    monkeypatch.setattr(
        resume_generation_requests,
        "complete_resume_generation_request",
        complete_request,
    )

    result = resume_generation_requests.complete(
        REQUEST_ID, completion_payload(), object()
    )

    assert result["status"] == "completed"


def test_incorrect_complete_claim_token_returns_409(monkeypatch) -> None:
    wrong_token = uuid4()

    def invalid(settings, request_id, claim_token, artifact):
        assert claim_token == wrong_token
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "complete_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.complete(
            REQUEST_ID,
            resume_generation_requests.ResumeGenerationRequestCompletion(
                claim_token=wrong_token,
                artifact=resume_generation_requests.ResumeGenerationArtifactCreate(
                    **artifact_values()
                ),
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_fail_requires_correct_claim_token(monkeypatch) -> None:
    def transition(
        settings,
        request_id,
        status,
        failure_reason=None,
        worker_id=None,
        claim_token=None,
    ):
        assert claim_token == CLAIM_TOKEN
        return request_record(
            status=status,
            failure_reason=failure_reason,
            processing_started_at=NOW,
            failed_at=NOW,
            worker_id="worker-a",
            attempt_count=1,
        )

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        transition,
    )

    result = resume_generation_requests.fail(
        REQUEST_ID,
        resume_generation_requests.ResumeGenerationRequestFailure(
            claim_token=CLAIM_TOKEN,
            failure_reason="worker failed",
        ),
        object(),
    )

    assert result["status"] == "failed"
    assert result["failure_reason"] == "worker failed"


def test_incorrect_fail_claim_token_returns_409(monkeypatch) -> None:
    wrong_token = uuid4()

    def invalid(
        settings,
        request_id,
        status,
        failure_reason=None,
        worker_id=None,
        claim_token=None,
    ):
        assert claim_token == wrong_token
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.fail(
            REQUEST_ID,
            resume_generation_requests.ResumeGenerationRequestFailure(
                claim_token=wrong_token,
                failure_reason="worker failed",
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_transition_missing_request_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None, worker_id=None, claim_token=None: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.claim(
            REQUEST_ID,
            resume_generation_requests.ResumeGenerationRequestClaim(worker_id="w1"),
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "resume generation request not found"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            resume_generation_requests.complete,
            completion_payload(),
        ),
        (
            resume_generation_requests.fail,
            resume_generation_requests.ResumeGenerationRequestFailure(
                claim_token=CLAIM_TOKEN,
                failure_reason="boom",
            ),
        ),
    ],
)
def test_finish_transition_missing_request_returns_404(
    endpoint,
    payload,
    monkeypatch,
) -> None:
    if endpoint is resume_generation_requests.complete:
        monkeypatch.setattr(
            resume_generation_requests,
            "complete_resume_generation_request",
            lambda settings, request_id, claim_token, artifact: None,
        )
    else:
        monkeypatch.setattr(
            resume_generation_requests,
            "transition_resume_generation_request",
            lambda settings, request_id, status, failure_reason=None, worker_id=None, claim_token=None: None,
        )

    with pytest.raises(HTTPException) as exc:
        endpoint(REQUEST_ID, payload, object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "resume generation request not found"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        (
            resume_generation_requests.fail,
            resume_generation_requests.ResumeGenerationRequestFailure(
                failure_reason="boom",
            ),
        ),
    ],
)
def test_missing_finish_claim_token_returns_409(
    endpoint,
    payload,
    monkeypatch,
) -> None:
    def invalid(
        settings,
        request_id,
        status,
        failure_reason=None,
        worker_id=None,
        claim_token=None,
    ):
        assert claim_token is None
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        endpoint(REQUEST_ID, payload, object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_completion_requires_claim_token_and_artifact() -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestCompletion()

    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestCompletion(
            claim_token=CLAIM_TOKEN,
        )


def test_blank_failure_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestFailure(
            failure_reason="   ",
        )


class FakeCursor:
    def __init__(self, results):
        self.results = iter(results)
        self.queries: list[str] = []
        self.parameters: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchone(self):
        return next(self.results)


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.cursor_instance


def test_create_resume_generation_request_rejects_missing_resume(monkeypatch) -> None:
    cursor = FakeCursor([{"id": JOB_ID}, None])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    with pytest.raises(db.SourceResumeNotFound):
        db.create_resume_generation_request(object(), JOB_ID, RESUME_ID)

    statements = "\n".join(cursor.queries).lower()
    assert "from resumes" in statements
    assert "insert into resume_generation_requests" not in statements


def test_create_resume_generation_request_writes_audit_event(monkeypatch) -> None:
    audit = []
    cursor = FakeCursor(
        [{"id": JOB_ID}, {"id": RESUME_ID}, {"id": APPROVAL_ID}, None, request_record()]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    result = db.create_resume_generation_request(object(), JOB_ID, RESUME_ID)

    assert result == request_record()
    assert "resume_id" in cursor.queries[-1]
    assert audit == [
        (
            "resume_generation.requested",
            "resume_generation_request",
            REQUEST_ID,
            {
                "job_id": str(JOB_ID),
                "approval_id": str(APPROVAL_ID),
                "resume_id": str(RESUME_ID),
                "request_id": str(REQUEST_ID),
                "status": "queued",
            },
        )
    ]


@pytest.mark.parametrize(
    ("current_status", "new_status", "expected_action"),
    [
        ("queued", "processing", "resume_generation.claimed"),
        ("processing", "completed", "resume_generation.completed"),
        ("processing", "failed", "resume_generation.failed"),
    ],
)
def test_transition_writes_audit_event(
    current_status,
    new_status,
    expected_action,
    monkeypatch,
) -> None:
    audit = []
    previous = request_record(
        status=current_status,
        processing_started_at=NOW if current_status == "processing" else None,
        worker_id="worker-a" if current_status == "processing" else None,
        claim_token=CLAIM_TOKEN if current_status == "processing" else None,
        attempt_count=1 if current_status == "processing" else 0,
    )
    updated = request_record(
        status=new_status,
        processing_started_at=NOW,
        completed_at=NOW if new_status == "completed" else None,
        failed_at=NOW if new_status == "failed" else None,
        failure_reason="boom" if new_status == "failed" else None,
        worker_id="worker-a",
        claim_token=CLAIM_TOKEN,
        attempt_count=1,
    )
    cursor = FakeCursor([previous, updated])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(db, "uuid4", lambda: CLAIM_TOKEN)
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    result = db.transition_resume_generation_request(
        object(),
        REQUEST_ID,
        new_status,
        "boom" if new_status == "failed" else None,
        "worker-a" if new_status == "processing" else None,
        CLAIM_TOKEN if new_status in {"completed", "failed"} else None,
    )

    assert result == updated
    metadata = {
        "request_id": str(REQUEST_ID),
        "job_id": str(JOB_ID),
        "previous_status": current_status,
        "new_status": new_status,
    }
    if new_status == "failed":
        metadata["failure_reason"] = "boom"
    if new_status == "processing":
        metadata["worker_id"] = "worker-a"
        metadata["attempt_count"] = 1
    assert audit == [
        (
            expected_action,
            "resume_generation_request",
            REQUEST_ID,
            metadata,
        )
    ]
    assert all("claim_token" not in event_metadata for *_, event_metadata in audit)


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [
        ("queued", "completed"),
        ("queued", "failed"),
        ("processing", "processing"),
        ("completed", "processing"),
        ("completed", "completed"),
        ("completed", "failed"),
        ("failed", "processing"),
        ("failed", "completed"),
        ("failed", "failed"),
    ],
)
def test_invalid_db_transitions_are_rejected(
    current_status,
    new_status,
    monkeypatch,
) -> None:
    cursor = FakeCursor([request_record(status=current_status)])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    with pytest.raises(db.InvalidResumeGenerationRequestTransition):
        db.transition_resume_generation_request(
            object(),
            REQUEST_ID,
            new_status,
            "boom" if new_status == "failed" else None,
        )


def test_duplicate_claim_uses_row_lock_and_rejects_without_update_or_audit(
    monkeypatch,
) -> None:
    audit = []
    cursor = FakeCursor(
        [
            request_record(
                status="processing",
                processing_started_at=NOW,
                worker_id="worker-a",
                claim_token=CLAIM_TOKEN,
                attempt_count=1,
            )
        ]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    with pytest.raises(db.InvalidResumeGenerationRequestTransition):
        db.transition_resume_generation_request(
            object(),
            REQUEST_ID,
            "processing",
            worker_id="worker-b",
        )

    assert len(cursor.queries) == 1
    assert "FOR UPDATE" in cursor.queries[0]
    statements = "\n".join(cursor.queries).lower()
    assert "update resume_generation_requests" not in statements
    assert audit == []


@pytest.mark.parametrize(
    ("new_status", "failure_reason"),
    [
        ("completed", None),
        ("failed", "worker failed"),
    ],
)
def test_finish_token_mismatch_rejects_without_update_or_audit(
    new_status,
    failure_reason,
    monkeypatch,
) -> None:
    audit = []
    cursor = FakeCursor(
        [
            request_record(
                status="processing",
                processing_started_at=NOW,
                worker_id="worker-a",
                claim_token=CLAIM_TOKEN,
                attempt_count=1,
            )
        ]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    with pytest.raises(db.InvalidResumeGenerationRequestTransition):
        db.transition_resume_generation_request(
            object(),
            REQUEST_ID,
            new_status,
            failure_reason,
            claim_token=uuid4(),
        )

    assert len(cursor.queries) == 1
    assert "FOR UPDATE" in cursor.queries[0]
    statements = "\n".join(cursor.queries).lower()
    assert "update resume_generation_requests" not in statements
    assert audit == []


@pytest.mark.parametrize("finished_status", ["completed", "failed"])
def test_new_request_allowed_after_completed_or_failed(
    finished_status,
    monkeypatch,
) -> None:
    cursor = FakeCursor(
        [
            {"id": JOB_ID},
            {"id": RESUME_ID},
            {"id": APPROVAL_ID},
            None,
            request_record(status="queued"),
        ]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(db, "_write_audit_log", lambda *args, **kwargs: None)

    result = db.create_resume_generation_request(object(), JOB_ID, RESUME_ID)

    assert result["status"] == "queued"


@pytest.mark.parametrize("active_status", ["queued", "processing"])
def test_new_request_blocked_during_queued_or_processing(
    active_status,
    monkeypatch,
) -> None:
    cursor = FakeCursor(
        [
            {"id": JOB_ID},
            {"id": RESUME_ID},
            {"id": APPROVAL_ID},
            request_record(status=active_status),
        ]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    with pytest.raises(db.ActiveResumeGenerationRequestExists):
        db.create_resume_generation_request(object(), JOB_ID, RESUME_ID)


def test_request_queue_does_not_touch_applications_documents_minio_or_llm(
    monkeypatch,
) -> None:
    cursor = FakeCursor(
        [{"id": JOB_ID}, {"id": RESUME_ID}, {"id": APPROVAL_ID}, None, request_record()]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(db, "_write_audit_log", lambda *args, **kwargs: None)

    db.create_resume_generation_request(object(), JOB_ID, RESUME_ID)

    statements = "\n".join(cursor.queries).lower()
    assert "resume_generation_requests" in statements
    assert "applications" not in statements
    assert "generated_documents" not in statements
    assert "minio" not in statements
    assert "openai" not in statements


def processing_request(**overrides):
    return request_record(
        status="processing",
        processing_started_at=NOW,
        worker_id="worker-a",
        claim_token=CLAIM_TOKEN,
        attempt_count=1,
    ) | overrides


def test_complete_atomically_creates_artifact_with_safe_audit(monkeypatch) -> None:
    completed = processing_request(status="completed", completed_at=NOW)
    cursor = FakeCursor([processing_request(), artifact_record(), completed])
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    result = db.complete_resume_generation_request(
        object(), REQUEST_ID, CLAIM_TOKEN, artifact_values()
    )

    assert result == completed | {"artifact": artifact_record()}
    statements = "\n".join(cursor.queries).lower()
    assert statements.index("insert into resume_generation_artifacts") < statements.index(
        "update resume_generation_requests"
    )
    assert cursor.parameters[1][:3] == (REQUEST_ID, JOB_ID, RESUME_ID)
    assert audit == [
        (
            "resume_generation.completed",
            "resume_generation_request",
            REQUEST_ID,
            {
                "request_id": str(REQUEST_ID),
                "artifact_id": str(ARTIFACT_ID),
                "storage_bucket": "generated-resumes",
                "storage_key": f"requests/{REQUEST_ID}/resume.md",
                "sha256": SHA256,
                "size_bytes": 1234,
                "provider": "configured-provider",
                "model": "configured-model",
                "model_version": "configured-model-v1",
                "input_tokens": 100,
                "output_tokens": 200,
                "latency_ms": 300,
                "finish_reason": "stop",
            },
        )
    ]
    assert "claim_token" not in str(audit)
    assert "content" not in audit[0][3]


def test_get_artifact_returns_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "get_resume_generation_artifact",
        lambda settings, request_id: artifact_record(),
    )

    assert resume_generation_requests.get_artifact(REQUEST_ID, object()) == artifact_record()


def test_get_artifact_missing_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "get_resume_generation_artifact",
        lambda settings, request_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.get_artifact(REQUEST_ID, object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "resume generation artifact not found"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"size_bytes": -1},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"latency_ms": -1},
    ],
)
def test_artifact_model_rejects_invalid_checksum_and_metrics(overrides) -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationArtifactCreate(
            **artifact_values(**overrides)
        )


@pytest.mark.parametrize(
    "existing",
    [
        processing_request(),
        processing_request(resume_id=None),
        request_record(status="queued", claim_token=CLAIM_TOKEN),
    ],
    ids=["invalid-token", "missing-resume", "not-processing"],
)
def test_atomic_completion_rejects_invalid_claimed_request(existing, monkeypatch) -> None:
    cursor = FakeCursor([existing])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    token = uuid4() if existing["resume_id"] is not None else CLAIM_TOKEN
    with pytest.raises(db.InvalidResumeGenerationRequestTransition):
        db.complete_resume_generation_request(
            object(), REQUEST_ID, token, artifact_values()
        )

    assert len(cursor.queries) == 1


class ArtifactConflictCursor(FakeCursor):
    def execute(self, query, parameters=None):
        super().execute(query, parameters)
        if "INSERT INTO resume_generation_artifacts" in query:
            raise db.UniqueViolation()


class RecordingConnection(FakeConnection):
    def __init__(self, cursor):
        super().__init__(cursor)
        self.exit_args = None

    def __exit__(self, *args):
        self.exit_args = args
        return None


@pytest.mark.parametrize("conflict", ["request", "storage-path"])
def test_artifact_conflict_rolls_back_without_completion(conflict, monkeypatch) -> None:
    cursor = ArtifactConflictCursor([processing_request()])
    connection = RecordingConnection(cursor)
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(db.psycopg, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(db.ResumeGenerationArtifactConflict):
        db.complete_resume_generation_request(
            object(), REQUEST_ID, CLAIM_TOKEN, artifact_values()
        )

    statements = "\n".join(cursor.queries).lower()
    assert "insert into resume_generation_artifacts" in statements
    assert "update resume_generation_requests" not in statements
    assert connection.exit_args[0] is db.ResumeGenerationArtifactConflict


def test_completion_artifact_conflict_returns_409(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "complete_resume_generation_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            db.ResumeGenerationArtifactConflict
        ),
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.complete(REQUEST_ID, completion_payload(), object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "resume generation artifact already exists"


def test_artifact_contract_contains_no_generated_content_or_credentials() -> None:
    fields = set(resume_generation_requests.ResumeGenerationArtifact.model_fields)
    assert "content" not in fields
    assert "generated_resume_content" not in fields
    assert "credentials" not in fields

    migration = Path(
        "deploy/base/postgres/migrations/007_resume_generation_artifacts.sql"
    ).read_text().lower()
    assert "generated_resume_content" not in migration
    assert "minio" not in migration


def test_migration_007_defines_artifact_constraints_and_foreign_keys() -> None:
    sql = Path(
        "deploy/base/postgres/migrations/007_resume_generation_artifacts.sql"
    ).read_text()

    assert "CREATE TABLE IF NOT EXISTS resume_generation_artifacts" in sql
    assert "request_id UUID NOT NULL UNIQUE REFERENCES resume_generation_requests(id)" in sql
    assert "job_id UUID NOT NULL REFERENCES jobs(id)" in sql
    assert "source_resume_id UUID NOT NULL REFERENCES resumes(id)" in sql
    assert "sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "size_bytes >= 0" in sql
    assert "input_tokens >= 0" in sql
    assert "output_tokens >= 0" in sql
    assert "latency_ms >= 0" in sql
    assert "UNIQUE (storage_bucket, storage_key)" in sql
