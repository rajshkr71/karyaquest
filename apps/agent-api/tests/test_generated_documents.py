from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from agent_api import db
from agent_api.main import app
from agent_api.settings import get_settings

client = TestClient(app)
DOCUMENT_ID = UUID("a4f85bc3-94b3-49b8-80eb-e664eb9f8af2")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
RESUME_ID = UUID("419f8064-dce7-4e2e-8062-0d93c56026fd")
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def document_record(**overrides):
    return {
        "id": DOCUMENT_ID,
        "job_id": JOB_ID,
        "resume_id": RESUME_ID,
        "document_type": "resume",
        "storage_path": "documents/resume.pdf",
        "checksum": "sha256:abc123",
        "model_used": None,
        "created_at": NOW,
    } | overrides


def setup_function() -> None:
    app.dependency_overrides[get_settings] = lambda: object()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_generated_document(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.generated_documents.create_generated_document",
        lambda settings, values: document_record(**values),
    )

    response = client.post(
        "/generated-documents",
        json={
            "job_id": str(JOB_ID),
            "resume_id": str(RESUME_ID),
            "document_type": "resume",
            "storage_path": "documents/resume.pdf",
            "checksum": "sha256:abc123",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(DOCUMENT_ID)
    assert "content" not in response.json()


def test_list_generated_documents(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.generated_documents.list_generated_documents",
        lambda settings: [document_record()],
    )

    response = client.get("/generated-documents")

    assert response.status_code == 200
    assert response.json()[0]["document_type"] == "resume"


def test_get_generated_document(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.generated_documents.get_generated_document",
        lambda settings, document_id: document_record(),
    )

    response = client.get(f"/generated-documents/{DOCUMENT_ID}")

    assert response.status_code == 200
    assert response.json()["storage_path"] == "documents/resume.pdf"


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


def test_create_generated_document_audit_is_content_safe(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(document_record()),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    db.create_generated_document(
        object(),
        {
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "document_type": "resume",
            "storage_path": "documents/resume.pdf",
            "checksum": "sha256:abc123",
            "model_used": None,
        },
    )

    assert audit == [
        (
            "generated_document.created",
            "generated_document",
            DOCUMENT_ID,
            {
                "document_type": "resume",
                "job_id": str(JOB_ID),
                "resume_id": str(RESUME_ID),
                "checksum": "sha256:abc123",
            },
        )
    ]
