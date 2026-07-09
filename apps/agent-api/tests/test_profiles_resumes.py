from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from agent_api import db
from agent_api.main import app
from agent_api.settings import get_settings

client = TestClient(app)
PROFILE_ID = UUID("4d0882bf-30ac-4e34-835b-d36b17e902c1")
RESUME_ID = UUID("419f8064-dce7-4e2e-8062-0d93c56026fd")
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def profile_record(**overrides):
    return {
        "id": PROFILE_ID,
        "name": "Primary profile",
        "content": {"skills": ["Python"]},
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def resume_record(**overrides):
    return {
        "id": RESUME_ID,
        "name": "Backend resume",
        "base_profile_id": PROFILE_ID,
        "content": "User supplied resume text.",
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    } | overrides


def setup_function() -> None:
    app.dependency_overrides[get_settings] = lambda: object()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.profiles.create_profile",
        lambda settings, values: profile_record(**values),
    )

    response = client.post(
        "/profiles",
        json={"name": "Primary profile", "content": {"skills": ["Python"]}},
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(PROFILE_ID)


def test_list_profiles(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.profiles.list_profiles",
        lambda settings: [profile_record()],
    )

    response = client.get("/profiles")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Primary profile"


def test_get_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.profiles.get_profile",
        lambda settings, profile_id: profile_record(),
    )

    response = client.get(f"/profiles/{PROFILE_ID}")

    assert response.status_code == 200
    assert response.json()["content"] == {"skills": ["Python"]}


def test_patch_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.profiles.update_profile",
        lambda settings, profile_id, values: profile_record(**values),
    )

    response = client.patch(
        f"/profiles/{PROFILE_ID}",
        json={"name": "Updated profile"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated profile"


def test_create_resume_preserves_submitted_content(monkeypatch) -> None:
    captured = {}

    def fake_create(settings, values):
        captured.update(values)
        return resume_record(**values)

    monkeypatch.setattr("agent_api.resumes.create_resume", fake_create)
    response = client.post(
        "/resumes",
        json={
            "name": "Backend resume",
            "base_profile_id": str(PROFILE_ID),
            "content": "User supplied resume text.",
        },
    )

    assert response.status_code == 201
    assert captured["content"] == "User supplied resume text."
    assert datetime.fromisoformat(response.json()["updated_at"]) == NOW


def test_list_resumes(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.resumes.list_resumes",
        lambda settings: [resume_record()],
    )

    response = client.get("/resumes")

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(RESUME_ID)
    assert datetime.fromisoformat(response.json()[0]["updated_at"]) == NOW


def test_get_resume(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.resumes.get_resume",
        lambda settings, resume_id: resume_record(),
    )

    response = client.get(f"/resumes/{RESUME_ID}")

    assert response.status_code == 200
    assert response.json()["content"] == "User supplied resume text."
    assert datetime.fromisoformat(response.json()["updated_at"]) == NOW


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


def capture_audit(monkeypatch, result):
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(result),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )
    return audit


def test_profile_create_audit(monkeypatch) -> None:
    audit = capture_audit(monkeypatch, profile_record())

    db.create_profile(
        object(),
        {"name": "Primary profile", "content": {"skills": ["Python"]}},
    )

    assert audit == [
        ("profile.created", "profile", PROFILE_ID, {"name": "Primary profile"})
    ]


def test_profile_update_audit(monkeypatch) -> None:
    audit = capture_audit(
        monkeypatch,
        profile_record(name="Updated profile"),
    )

    db.update_profile(object(), PROFILE_ID, {"name": "Updated profile"})

    assert audit == [
        (
            "profile.updated",
            "profile",
            PROFILE_ID,
            {"changed_fields": ["name"]},
        )
    ]


def test_resume_create_audit(monkeypatch) -> None:
    audit = capture_audit(monkeypatch, resume_record())

    db.create_resume(
        object(),
        {
            "name": "Backend resume",
            "base_profile_id": PROFILE_ID,
            "content": "User supplied resume text.",
            "version": 1,
        },
    )

    assert audit == [
        (
            "resume.created",
            "resume",
            RESUME_ID,
            {
                "name": "Backend resume",
                "base_profile_id": str(PROFILE_ID),
                "version": 1,
            },
        )
    ]
