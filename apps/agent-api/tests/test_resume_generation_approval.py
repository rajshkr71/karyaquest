from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

from agent_api import db, resume_generation_approvals

APPROVAL_ID = UUID("6f5be64c-b698-4024-b5df-5a6b730e2807")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def approval_record(**overrides):
    record = {
        "id": APPROVAL_ID,
        "job_id": JOB_ID,
        "approved_at": NOW,
        "created_at": NOW,
    }
    return record | overrides


def test_approve_resume_generation_route_returns_approval(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_approvals,
        "approve_resume_generation",
        lambda settings, job_id: approval_record(),
    )

    result = resume_generation_approvals.approve_resume_generation_for_job(
        JOB_ID,
        object(),
    )

    assert result["id"] == APPROVAL_ID
    assert result["job_id"] == JOB_ID
    assert result["approved_at"] == NOW
    assert result["created_at"] == NOW


def test_list_resume_generation_approvals(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_approvals,
        "list_resume_generation_approvals",
        lambda settings: [approval_record()],
    )

    result = resume_generation_approvals.list_all(object())

    assert result == [approval_record()]


def test_approve_resume_generation_route_rejects_duplicates(monkeypatch) -> None:
    def duplicate(settings, job_id):
        raise db.ResumeGenerationApprovalExists

    monkeypatch.setattr(
        resume_generation_approvals,
        "approve_resume_generation",
        duplicate,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_approvals.approve_resume_generation_for_job(
            JOB_ID,
            object(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "resume generation approval already granted"


def test_approve_resume_generation_route_missing_job_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        resume_generation_approvals,
        "approve_resume_generation",
        lambda settings, job_id: None,
    )

    with pytest.raises(HTTPException) as exc:
        resume_generation_approvals.approve_resume_generation_for_job(
            JOB_ID,
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "job not found"


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

    def fetchall(self):
        return list(self.results)


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.cursor_instance


def test_approve_resume_generation_writes_audit_event(monkeypatch) -> None:
    audit = []
    cursor = FakeCursor([{"id": JOB_ID}, None, approval_record()])
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

    result = db.approve_resume_generation(object(), JOB_ID)

    assert result == approval_record()
    assert audit == [
        (
            "resume_generation.approved",
            "resume_generation_approval",
            APPROVAL_ID,
            {
                "job_id": str(JOB_ID),
                "approval_id": str(APPROVAL_ID),
                "approval_state": "approved",
            },
        )
    ]


def test_approve_resume_generation_prevents_duplicate_approval(monkeypatch) -> None:
    cursor = FakeCursor([{"id": JOB_ID}, approval_record()])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )

    with pytest.raises(db.ResumeGenerationApprovalExists):
        db.approve_resume_generation(object(), JOB_ID)


def test_approve_resume_generation_does_not_create_application_row(monkeypatch) -> None:
    cursor = FakeCursor([{"id": JOB_ID}, None, approval_record()])
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(db, "_write_audit_log", lambda *args, **kwargs: None)

    db.approve_resume_generation(object(), JOB_ID)

    statements = "\n".join(cursor.queries).lower()
    assert "resume_generation_approvals" in statements
    assert "applications" not in statements
