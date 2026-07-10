from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

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
