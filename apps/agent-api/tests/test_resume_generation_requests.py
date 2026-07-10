from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent_api import db, resume_generation_requests

REQUEST_ID = UUID("2ecee968-87dc-43bf-bf6b-10b5c4cfd379")
APPROVAL_ID = UUID("6f5be64c-b698-4024-b5df-5a6b730e2807")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def request_record(**overrides):
    record = {
        "id": REQUEST_ID,
        "job_id": JOB_ID,
        "approval_id": APPROVAL_ID,
        "resume_id": None,
        "status": "queued",
        "failure_reason": None,
        "processing_started_at": None,
        "completed_at": None,
        "failed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return record | overrides


def test_create_resume_generation_request_route_returns_queued(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        lambda settings, job_id: request_record(),
    )

    result = resume_generation_requests.create_for_job(JOB_ID, object())

    assert result["job_id"] == JOB_ID
    assert result["approval_id"] == APPROVAL_ID
    assert result["status"] == "queued"


def test_create_resume_generation_request_missing_job_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        lambda settings, job_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(JOB_ID, object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "job not found"


def test_create_resume_generation_request_missing_approval_returns_409(
    monkeypatch,
) -> None:
    def missing_approval(settings, job_id):
        raise db.ResumeGenerationApprovalMissing

    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        missing_approval,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(JOB_ID, object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "resume generation approval is required"


def test_create_resume_generation_request_duplicate_active_returns_409(
    monkeypatch,
) -> None:
    def duplicate(settings, job_id):
        raise db.ActiveResumeGenerationRequestExists

    monkeypatch.setattr(
        resume_generation_requests,
        "create_resume_generation_request",
        duplicate,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.create_for_job(JOB_ID, object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "an active resume generation request already exists"


def test_list_resume_generation_requests(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "list_resume_generation_requests",
        lambda settings: [request_record()],
    )

    assert resume_generation_requests.list_all(object()) == [request_record()]


def test_get_resume_generation_request(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "get_resume_generation_request",
        lambda settings, request_id: request_record(),
    )

    assert resume_generation_requests.get(REQUEST_ID, object()) == request_record()


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


@pytest.mark.parametrize(
    ("endpoint", "new_status"),
    [
        (resume_generation_requests.start, "processing"),
        (resume_generation_requests.complete, "completed"),
    ],
)
def test_valid_non_failure_transitions(endpoint, new_status, monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None: request_record(
            status=status,
        ),
    )

    result = endpoint(REQUEST_ID, object())

    assert result["status"] == new_status


def test_valid_failed_transition(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None: request_record(
            status=status,
            failure_reason=failure_reason,
            failed_at=NOW,
            processing_started_at=NOW,
        ),
    )

    result = resume_generation_requests.fail(
        REQUEST_ID,
        resume_generation_requests.ResumeGenerationRequestFailure(
            failure_reason=" upstream failed ",
        ),
        object(),
    )

    assert result["status"] == "failed"
    assert result["failure_reason"] == "upstream failed"


@pytest.mark.parametrize(
    "endpoint",
    [
        resume_generation_requests.start,
        resume_generation_requests.complete,
    ],
)
def test_invalid_non_failure_transitions_return_409(endpoint, monkeypatch) -> None:
    def invalid(settings, request_id, status, failure_reason=None):
        raise db.InvalidResumeGenerationRequestTransition

    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        invalid,
    )

    with pytest.raises(HTTPException) as exc:
        endpoint(REQUEST_ID, object())

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_invalid_failure_transition_returns_409(monkeypatch) -> None:
    def invalid(settings, request_id, status, failure_reason=None):
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
                failure_reason="boom",
            ),
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invalid resume generation request transition"


def test_transition_missing_request_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_requests,
        "transition_resume_generation_request",
        lambda settings, request_id, status, failure_reason=None: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_requests.start(REQUEST_ID, object())

    assert exc.value.status_code == 404
    assert exc.value.detail == "resume generation request not found"


def test_blank_failure_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        resume_generation_requests.ResumeGenerationRequestFailure(
            failure_reason="   ",
        )


class FakeCursor:
    def __init__(self, results):
        self.results = iter(results)
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)

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


def test_create_resume_generation_request_writes_audit_event(monkeypatch) -> None:
    audit = []
    cursor = FakeCursor([{"id": JOB_ID}, {"id": APPROVAL_ID}, None, request_record()])
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

    result = db.create_resume_generation_request(object(), JOB_ID)

    assert result == request_record()
    assert audit == [
        (
            "resume_generation.requested",
            "resume_generation_request",
            REQUEST_ID,
            {
                "job_id": str(JOB_ID),
                "approval_id": str(APPROVAL_ID),
                "request_id": str(REQUEST_ID),
                "status": "queued",
            },
        )
    ]


@pytest.mark.parametrize(
    ("current_status", "new_status", "expected_action"),
    [
        ("queued", "processing", "resume_generation.processing_started"),
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
    previous = request_record(status=current_status)
    updated = request_record(
        status=new_status,
        processing_started_at=NOW,
        completed_at=NOW if new_status == "completed" else None,
        failed_at=NOW if new_status == "failed" else None,
        failure_reason="boom" if new_status == "failed" else None,
    )
    cursor = FakeCursor([previous, updated])
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

    result = db.transition_resume_generation_request(
        object(),
        REQUEST_ID,
        new_status,
        "boom" if new_status == "failed" else None,
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
    assert audit == [
        (
            expected_action,
            "resume_generation_request",
            REQUEST_ID,
            metadata,
        )
    ]


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


@pytest.mark.parametrize("finished_status", ["completed", "failed"])
def test_new_request_allowed_after_completed_or_failed(
    finished_status,
    monkeypatch,
) -> None:
    cursor = FakeCursor(
        [
            {"id": JOB_ID},
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

    result = db.create_resume_generation_request(object(), JOB_ID)

    assert result["status"] == "queued"


@pytest.mark.parametrize("active_status", ["queued", "processing"])
def test_new_request_blocked_during_queued_or_processing(
    active_status,
    monkeypatch,
) -> None:
    cursor = FakeCursor(
        [{"id": JOB_ID}, {"id": APPROVAL_ID}, request_record(status=active_status)]
    )
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    with pytest.raises(db.ActiveResumeGenerationRequestExists):
        db.create_resume_generation_request(object(), JOB_ID)


def test_request_queue_does_not_touch_applications_documents_minio_or_llm(
    monkeypatch,
) -> None:
    cursor = FakeCursor([{"id": JOB_ID}, {"id": APPROVAL_ID}, None, request_record()])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(db, "_write_audit_log", lambda *args, **kwargs: None)

    db.create_resume_generation_request(object(), JOB_ID)

    statements = "\n".join(cursor.queries).lower()
    assert "resume_generation_requests" in statements
    assert "applications" not in statements
    assert "generated_documents" not in statements
    assert "minio" not in statements
    assert "openai" not in statements
