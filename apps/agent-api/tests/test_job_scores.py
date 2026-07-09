from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from agent_api import db
from agent_api.main import app
from agent_api.settings import get_settings

client = TestClient(app)
SCORE_ID = UUID("c00b2f2c-31ad-4ee9-84ad-a31718353dbb")
JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
RESUME_ID = UUID("419f8064-dce7-4e2e-8062-0d93c56026fd")
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def score_record(**overrides):
    return {
        "id": SCORE_ID,
        "job_id": JOB_ID,
        "resume_id": RESUME_ID,
        "score": 82,
        "strengths": ["Python", "APIs"],
        "gaps": ["Kubernetes"],
        "recommendation": "review",
        "model_used": None,
        "created_at": NOW,
    } | overrides


def setup_function() -> None:
    app.dependency_overrides[get_settings] = lambda: object()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_job_score(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_scores.create_job_score",
        lambda settings, values: score_record(**values),
    )

    response = client.post(
        "/job-scores",
        json={
            "job_id": str(JOB_ID),
            "resume_id": str(RESUME_ID),
            "score": 82,
            "strengths": ["Python", "APIs"],
            "gaps": ["Kubernetes"],
            "recommendation": "review",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(SCORE_ID)
    assert response.json()["score"] == 82


def test_list_job_scores(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_scores.list_job_scores",
        lambda settings: [score_record()],
    )

    response = client.get("/job-scores")

    assert response.status_code == 200
    assert response.json()[0]["job_id"] == str(JOB_ID)


def test_get_job_score(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_scores.get_job_score",
        lambda settings, score_id: score_record(),
    )

    response = client.get(f"/job-scores/{SCORE_ID}")

    assert response.status_code == 200
    assert response.json()["recommendation"] == "review"


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


def test_create_job_score_writes_content_safe_audit_event(monkeypatch) -> None:
    audit = []
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(score_record()),
    )
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, target_id, metadata, target_type="job": audit.append(
            (action, target_type, target_id, metadata)
        ),
    )

    db.create_job_score(
        object(),
        {
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "score": 82,
            "strengths": ["Python", "APIs"],
            "gaps": ["Kubernetes"],
            "recommendation": "review",
            "model_used": None,
        },
    )

    assert audit == [
        (
            "job.scored",
            "job",
            JOB_ID,
            {
                "job_id": str(JOB_ID),
                "resume_id": str(RESUME_ID),
                "score": 82,
                "recommendation": "review",
                "model_used": None,
            },
        )
    ]
