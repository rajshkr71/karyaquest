from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

from agent_api import db
from agent_api.job_imports import GreenhouseImport, import_greenhouse_jobs

JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
SOURCE_URL = "https://boards.greenhouse.io/acme/jobs/123"


def greenhouse_job():
    return {
        "id": 123,
        "title": "Platform Engineer",
        "location": {"name": "Toronto"},
        "content": "<p>Build &amp; operate APIs.</p>",
        "absolute_url": SOURCE_URL,
    }


def job_record(**overrides):
    return {
        "id": JOB_ID,
        "source": "greenhouse",
        "source_url": SOURCE_URL,
        "company": "Acme",
        "title": "Platform Engineer",
        "location": "Toronto",
        "remote_type": None,
        "description": "Build & operate APIs.",
        "required_skills": [],
        "preferred_skills": [],
        "salary_min": None,
        "salary_max": None,
        "detected_seniority": None,
        "status": "normalized",
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def test_greenhouse_board_import_fetches_public_jobs_and_normalizes(monkeypatch) -> None:
    fetched = []
    stored = []

    def fake_fetch(path):
        fetched.append(path)
        if path == "boards/acme":
            return {"name": "Acme"}
        return {"jobs": [greenhouse_job()]}

    monkeypatch.setattr("agent_api.job_imports._fetch_greenhouse_json", fake_fetch)
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: False,
    )
    monkeypatch.setattr(
        "agent_api.job_imports.create_manual_job",
        lambda settings, values: stored.append(values) or job_record(**values),
    )

    result = import_greenhouse_jobs(
        GreenhouseImport(board_token="acme"),
        object(),
    )

    assert fetched == ["boards/acme", "boards/acme/jobs?content=true"]
    assert result[0]["source"] == "greenhouse"
    assert stored[0]["company"] == "Acme"
    assert stored[0]["description"] == "Build & operate APIs."
    assert stored[0]["status"] == "normalized"


def test_greenhouse_job_url_imports_one_job(monkeypatch) -> None:
    fetched = []
    monkeypatch.setattr(
        "agent_api.job_imports._fetch_greenhouse_json",
        lambda path: fetched.append(path)
        or ({"name": "Acme"} if path == "boards/acme" else greenhouse_job()),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: False,
    )
    monkeypatch.setattr(
        "agent_api.job_imports.create_manual_job",
        lambda settings, values: job_record(**values),
    )

    result = import_greenhouse_jobs(
        GreenhouseImport(job_url=SOURCE_URL),
        object(),
    )

    assert fetched == ["boards/acme", "boards/acme/jobs/123"]
    assert len(result) == 1


def test_greenhouse_duplicate_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_imports._fetch_greenhouse_json",
        lambda path: (
            {"name": "Acme"}
            if path == "boards/acme"
            else {"jobs": [greenhouse_job()]}
        ),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: (
            source == "greenhouse" and source_url == SOURCE_URL
        ),
    )

    with pytest.raises(HTTPException) as exc:
        import_greenhouse_jobs(GreenhouseImport(board_token="acme"), object())

    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "job_url",
    [
        "https://example.com/acme/jobs/123",
        "http://boards.greenhouse.io/acme/jobs/123",
        "https://boards.greenhouse.io/acme",
    ],
)
def test_greenhouse_job_url_validation_errors(job_url: str) -> None:
    with pytest.raises(HTTPException) as exc:
        import_greenhouse_jobs(GreenhouseImport(job_url=job_url), object())

    assert exc.value.status_code == 422


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


def test_greenhouse_import_writes_content_safe_audit_events(monkeypatch) -> None:
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
            (action, metadata)
        ),
    )

    db.create_manual_job(
        object(),
        {
            "source": "greenhouse",
            "source_url": SOURCE_URL,
            "company": "Acme",
            "title": "Platform Engineer",
            "description": "Build & operate APIs.",
            "required_skills": [],
            "preferred_skills": [],
            "status": "normalized",
        },
    )

    assert [action for action, _ in audit] == ["job.imported", "job.normalized"]
    assert all("description" not in metadata for _, metadata in audit)
