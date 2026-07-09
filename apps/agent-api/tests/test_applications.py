from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from agent_api import db
from agent_api.main import app
from agent_api.settings import get_settings

client = TestClient(app)
APPLICATION_ID = UUID("4453b976-027a-42db-a8e5-3b7e7e4d9d13")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def application_record(**overrides):
    record = {
        "id": APPLICATION_ID,
        "job_id": JOB_ID,
        "status": "draft",
        "application_url": None,
        "submitted_at": None,
        "failure_reason": None,
        "manual_required_reason": None,
        "resume_document_id": None,
        "cover_letter_document_id": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return record | overrides


def setup_function() -> None:
    app.dependency_overrides[get_settings] = lambda: object()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_application(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.applications.create_application",
        lambda settings, values: application_record(**values),
    )

    response = client.post("/applications", json={"job_id": str(JOB_ID)})

    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_list_applications(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.applications.list_applications",
        lambda settings: [application_record()],
    )

    response = client.get("/applications")

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(APPLICATION_ID)


def test_get_missing_application_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.applications.get_application",
        lambda settings, application_id: None,
    )

    response = client.get(f"/applications/{APPLICATION_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}


def test_get_application(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.applications.get_application",
        lambda settings, application_id: application_record(),
    )

    response = client.get(f"/applications/{APPLICATION_ID}")

    assert response.status_code == 200
    assert response.json()["job_id"] == str(JOB_ID)


def test_patch_application(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.applications.update_application",
        lambda settings, application_id, values: application_record(**values),
    )

    response = client.patch(
        f"/applications/{APPLICATION_ID}",
        json={"status": "submitted"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


class FakeCursor:
    def __init__(self, results):
        self.results = iter(results)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, parameters):
        return None

    def fetchone(self):
        return next(self.results)


class FakeConnection:
    def __init__(self, results):
        self.results = results

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return FakeCursor(self.results)


def test_status_change_writes_audit_event(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(
            [{"status": "draft"}, application_record(status="submitted")]
        ),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    db.update_application(object(), APPLICATION_ID, {"status": "submitted"})

    assert audit == [
        (
            "application.status_changed",
            "application",
            APPLICATION_ID,
            {"old_status": "draft", "new_status": "submitted"},
        )
    ]


def test_non_status_change_does_not_write_audit_event(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(
            [
                {"status": "draft"},
                application_record(application_url="https://example.com"),
            ]
        ),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda *args, **kwargs: audit.append((args, kwargs)),
    )

    db.update_application(
        object(),
        APPLICATION_ID,
        {"application_url": "https://example.com"},
    )

    assert audit == []
