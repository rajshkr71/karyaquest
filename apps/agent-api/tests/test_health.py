from fastapi.testclient import TestClient

from agent_api.main import app
from agent_api.settings import get_settings


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agent-api"}


def test_readyz_returns_ok_when_database_is_ready(monkeypatch) -> None:
    app.dependency_overrides[get_settings] = lambda: object()
    monkeypatch.setattr("agent_api.main.check_postgres_ready", lambda settings: True)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}

    app.dependency_overrides.clear()


def test_readyz_returns_503_when_database_is_not_ready(monkeypatch) -> None:
    app.dependency_overrides[get_settings] = lambda: object()
    monkeypatch.setattr("agent_api.main.check_postgres_ready", lambda settings: False)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "database not ready"}

    app.dependency_overrides.clear()


def test_versionz_returns_tables_when_schema_is_visible(monkeypatch) -> None:
    app.dependency_overrides[get_settings] = lambda: object()
    monkeypatch.setattr(
        "agent_api.main.list_public_tables",
        lambda settings: ["applications", "jobs", "resumes"],
    )

    response = client.get("/versionz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ready",
        "tables": ["applications", "jobs", "resumes"],
    }

    app.dependency_overrides.clear()


def test_versionz_returns_503_when_schema_is_not_visible(monkeypatch) -> None:
    app.dependency_overrides[get_settings] = lambda: object()
    monkeypatch.setattr("agent_api.main.list_public_tables", lambda settings: [])

    response = client.get("/versionz")

    assert response.status_code == 503
    assert response.json() == {"detail": "database schema not visible"}

    app.dependency_overrides.clear()
