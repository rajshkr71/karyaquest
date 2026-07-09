from datetime import UTC, datetime
from uuid import UUID

from agent_api import db
from agent_api.job_imports import (
    ManualJobImport,
    import_manual_job,
    normalize_manual_job,
)

JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def job_record(**overrides):
    return {
        "id": JOB_ID,
        "source": "manual",
        "source_url": "https://example.com/jobs/1",
        "company": "Example Corp",
        "title": "Platform Engineer",
        "location": "Toronto",
        "remote_type": "hybrid",
        "description": "Build APIs.",
        "required_skills": ["Python"],
        "preferred_skills": ["Kubernetes"],
        "salary_min": None,
        "salary_max": None,
        "detected_seniority": None,
        "status": "normalized",
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def test_manual_import_normalizes_and_stores_job(monkeypatch) -> None:
    stored = []
    monkeypatch.setattr(
        "agent_api.job_imports.create_manual_job",
        lambda settings, values: stored.append(values) or job_record(**values),
    )
    payload = ManualJobImport(
        source_url="https://example.com/jobs/1",
        company=" Example Corp ",
        title=" Platform Engineer ",
        location=" Toronto ",
        remote_type=" hybrid ",
        description=" Build APIs. ",
        required_skills=[" Python ", "Python"],
        preferred_skills=[" Kubernetes "],
    )

    result = import_manual_job(payload, object())

    assert result["source"] == "manual"
    assert stored[0]["status"] == "normalized"
    assert stored[0]["company"] == "Example Corp"
    assert stored[0]["required_skills"] == ["Python"]


def test_complete_useful_fields_are_normalized() -> None:
    values = normalize_manual_job(
        ManualJobImport(
            source_url="https://example.com/jobs/1",
            company="Example Corp",
            title="Platform Engineer",
            description="Build APIs.",
        )
    )

    assert values["status"] == "normalized"


def test_missing_useful_fields_need_review() -> None:
    values = normalize_manual_job(
        ManualJobImport(source_url="https://example.com/jobs/1")
    )

    assert values["status"] == "needs_review"
    assert values["company"] == "Unknown company"
    assert values["title"] == "Untitled position"
    assert values["description"] == "Description not provided"


class FakeCursor:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, parameters):
        return None

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return FakeCursor(self.result)


def test_normalized_import_writes_content_safe_audit_events(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(job_record()),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_id, metadata)
        ),
    )

    db.create_manual_job(
        object(),
        {
            "source": "manual",
            "source_url": "https://example.com/jobs/1",
            "company": "Example Corp",
            "title": "Platform Engineer",
            "description": "Build APIs.",
            "required_skills": ["Python"],
            "preferred_skills": [],
            "status": "normalized",
        },
    )

    assert [event[0] for event in audit] == ["job.imported", "job.normalized"]
    assert all(event[1] == JOB_ID for event in audit)
    assert all("description" not in event[2] for event in audit)


def test_needs_review_import_only_writes_imported_event(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(
            job_record(status="needs_review")
        ),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            action
        ),
    )

    db.create_manual_job(
        object(),
        {
            "source": "manual",
            "source_url": "https://example.com/jobs/1",
            "company": "Unknown company",
            "title": "Untitled position",
            "description": "Description not provided",
            "required_skills": [],
            "preferred_skills": [],
            "status": "needs_review",
        },
    )

    assert audit == ["job.imported"]
