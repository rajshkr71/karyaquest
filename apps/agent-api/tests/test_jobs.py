from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from agent_api.main import app
from agent_api.settings import get_settings

client = TestClient(app)
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def job_record(**overrides):
    record = {
        "id": JOB_ID,
        "source": "example",
        "source_url": "https://example.com/jobs/1",
        "company": "Example Co",
        "title": "Python Developer",
        "location": "Toronto",
        "remote_type": "hybrid",
        "description": "Build useful software.",
        "required_skills": ["Python"],
        "preferred_skills": [],
        "salary_min": 100000,
        "salary_max": 130000,
        "detected_seniority": "senior",
        "status": "discovered",
        "created_at": NOW,
        "updated_at": NOW,
    }
    return record | overrides


def setup_function() -> None:
    app.dependency_overrides[get_settings] = lambda: object()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_job(monkeypatch) -> None:
    captured = {}

    def fake_create(settings, values):
        captured.update(values)
        return job_record()

    monkeypatch.setattr("agent_api.jobs.create_job", fake_create)
    response = client.post(
        "/jobs",
        json={
            "source": "example",
            "source_url": "https://example.com/jobs/1",
            "company": "Example Co",
            "title": "Python Developer",
            "location": "Toronto",
            "remote_type": "hybrid",
            "description": "Build useful software.",
            "required_skills": ["Python"],
            "salary_min": 100000,
            "salary_max": 130000,
            "detected_seniority": "senior",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(JOB_ID)
    assert captured["status"] == "discovered"
    assert captured["preferred_skills"] == []


def test_list_jobs(monkeypatch) -> None:
    monkeypatch.setattr("agent_api.jobs.list_jobs", lambda settings: [job_record()])

    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json()[0]["company"] == "Example Co"


def test_get_job(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.jobs.get_job",
        lambda settings, job_id: job_record() if job_id == JOB_ID else None,
    )

    response = client.get(f"/jobs/{JOB_ID}")

    assert response.status_code == 200
    assert response.json()["title"] == "Python Developer"


def test_get_missing_job_returns_404(monkeypatch) -> None:
    monkeypatch.setattr("agent_api.jobs.get_job", lambda settings, job_id: None)

    response = client.get(f"/jobs/{JOB_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


def test_update_job(monkeypatch) -> None:
    captured = {}

    def fake_update(settings, job_id, values):
        captured.update(values)
        return job_record(status=values["status"])

    monkeypatch.setattr("agent_api.jobs.update_job", fake_update)

    response = client.patch(f"/jobs/{JOB_ID}", json={"status": "reviewed"})

    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"
    assert captured == {"status": "reviewed"}


def test_empty_update_returns_422(monkeypatch) -> None:
    response = client.patch(f"/jobs/{JOB_ID}", json={})

    assert response.status_code == 422
    assert response.json() == {"detail": "at least one field is required"}


def test_update_rejects_null_for_required_database_column() -> None:
    response = client.patch(f"/jobs/{JOB_ID}", json={"company": None})

    assert response.status_code == 422


def test_delete_job(monkeypatch) -> None:
    monkeypatch.setattr("agent_api.jobs.delete_job", lambda settings, job_id: True)

    response = client.delete(f"/jobs/{JOB_ID}")

    assert response.status_code == 204
    assert response.content == b""


def test_delete_missing_job_returns_404(monkeypatch) -> None:
    monkeypatch.setattr("agent_api.jobs.delete_job", lambda settings, job_id: False)

    response = client.delete(f"/jobs/{JOB_ID}")

    assert response.status_code == 404
