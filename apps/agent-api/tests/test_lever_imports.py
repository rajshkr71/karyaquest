from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

from agent_api import db
from agent_api.job_imports import LeverImport, _fetch_lever_json, import_lever_job

JOB_ID = UUID("6b9894db-523e-4e5e-bd8b-cd3b5449a642")
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
SOURCE_URL = "https://jobs.lever.co/acme/posting-123"


def lever_job():
    return {
        "id": "posting-123",
        "text": "Platform Engineer",
        "hostedUrl": SOURCE_URL,
        "categories": {"location": "Toronto"},
        "description": "<p>Build &amp; operate APIs.</p>",
        "lists": [{"text": "About you", "content": "<p>You like Python.</p>"}],
    }


def job_record(**overrides):
    return {
        "id": JOB_ID,
        "source": "lever",
        "source_url": SOURCE_URL,
        "company": "acme",
        "title": "Platform Engineer",
        "location": "Toronto",
        "remote_type": None,
        "description": "Build & operate APIs. You like Python.",
        "required_skills": [],
        "preferred_skills": [],
        "salary_min": None,
        "salary_max": None,
        "detected_seniority": None,
        "status": "normalized",
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def test_lever_single_posting_import_normalizes(monkeypatch) -> None:
    fetched = []
    stored = []

    monkeypatch.setattr(
        "agent_api.job_imports._fetch_lever_json",
        lambda path: fetched.append(path) or lever_job(),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: False,
    )
    monkeypatch.setattr(
        "agent_api.job_imports.create_manual_job",
        lambda settings, values: stored.append(values) or job_record(**values),
    )

    result = import_lever_job(
        LeverImport(posting_url=SOURCE_URL),
        object(),
    )

    assert fetched == ["postings/acme/posting-123"]
    assert result["source"] == "lever"
    assert stored[0]["company"] == "acme"
    assert stored[0]["title"] == "Platform Engineer"
    assert stored[0]["description"] == "Build & operate APIs. You like Python."
    assert stored[0]["status"] == "normalized"


def test_lever_token_and_posting_id_imports_one_posting(monkeypatch) -> None:
    fetched = []
    monkeypatch.setattr(
        "agent_api.job_imports._fetch_lever_json",
        lambda path: fetched.append(path) or lever_job(),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: False,
    )
    monkeypatch.setattr(
        "agent_api.job_imports.create_manual_job",
        lambda settings, values: job_record(**values),
    )

    result = import_lever_job(
        LeverImport(company_token="acme", posting_id="posting-123"),
        object(),
    )

    assert fetched == ["postings/acme/posting-123"]
    assert result["source_url"] == SOURCE_URL


def test_lever_duplicate_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_imports._fetch_lever_json",
        lambda path: lever_job(),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.job_source_url_exists",
        lambda settings, source, source_url: (
            source == "lever" and source_url == SOURCE_URL
        ),
    )

    with pytest.raises(HTTPException) as exc:
        import_lever_job(LeverImport(posting_url=SOURCE_URL), object())

    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "posting_url",
    [
        "https://example.com/acme/posting-123",
        "http://jobs.lever.co/acme/posting-123",
        "https://jobs.lever.co/acme",
    ],
)
def test_lever_posting_url_validation_errors(posting_url: str) -> None:
    with pytest.raises(HTTPException) as exc:
        import_lever_job(LeverImport(posting_url=posting_url), object())

    assert exc.value.status_code == 422


def test_lever_token_validation_errors() -> None:
    with pytest.raises(HTTPException) as exc:
        import_lever_job(
            LeverImport(company_token="bad/token", posting_id="posting-123"),
            object(),
        )

    assert exc.value.status_code == 422


def test_lever_fetch_timeout_returns_504(monkeypatch) -> None:
    def timeout(request, timeout):
        raise TimeoutError("external timeout details")

    monkeypatch.setattr("agent_api.job_imports.urlopen", timeout)

    with pytest.raises(HTTPException) as exc:
        _fetch_lever_json("postings/acme/posting-123")

    assert exc.value.status_code == 504
    assert exc.value.detail == "Lever job data request timed out"


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


def test_lever_import_writes_content_safe_audit_events(monkeypatch) -> None:
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
            "source": "lever",
            "source_url": SOURCE_URL,
            "company": "acme",
            "title": "Platform Engineer",
            "description": "Build & operate APIs. You like Python.",
            "required_skills": [],
            "preferred_skills": [],
            "status": "normalized",
        },
    )

    assert [action for action, _ in audit] == ["job.imported", "job.normalized"]
    assert all("description" not in metadata for _, metadata in audit)
