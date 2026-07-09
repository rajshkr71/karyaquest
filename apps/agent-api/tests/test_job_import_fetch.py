import io
import json
from urllib.error import HTTPError, URLError

import pytest
from fastapi import HTTPException

from agent_api.job_imports import _fetch_greenhouse_json, _fetch_lever_json


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_public_job_fetch_converts_http_error_to_clean_502(monkeypatch) -> None:
    def fail(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "upstream failed",
            {},
            io.BytesIO(b"secret external response body"),
        )

    monkeypatch.setattr("agent_api.job_imports.urlopen", fail)

    with pytest.raises(HTTPException) as exc:
        _fetch_greenhouse_json("boards/acme")

    assert exc.value.status_code == 502
    assert exc.value.detail == "Greenhouse job data could not be fetched"
    assert "secret" not in exc.value.detail


def test_public_job_fetch_converts_url_error_to_clean_502(monkeypatch) -> None:
    def fail(request, timeout):
        raise URLError("connection refused with internal network detail")

    monkeypatch.setattr("agent_api.job_imports.urlopen", fail)

    with pytest.raises(HTTPException) as exc:
        _fetch_lever_json("postings/acme/posting-123")

    assert exc.value.status_code == 502
    assert exc.value.detail == "Lever job data could not be fetched"


def test_public_job_fetch_converts_timeout_to_504(monkeypatch) -> None:
    def fail(request, timeout):
        raise TimeoutError("external timeout details")

    monkeypatch.setattr("agent_api.job_imports.urlopen", fail)

    with pytest.raises(HTTPException) as exc:
        _fetch_lever_json("postings/acme/posting-123")

    assert exc.value.status_code == 504
    assert exc.value.detail == "Lever job data request timed out"


def test_public_job_fetch_converts_url_timeout_to_504(monkeypatch) -> None:
    def fail(request, timeout):
        raise URLError(TimeoutError("external timeout details"))

    monkeypatch.setattr("agent_api.job_imports.urlopen", fail)

    with pytest.raises(HTTPException) as exc:
        _fetch_greenhouse_json("boards/acme")

    assert exc.value.status_code == 504
    assert exc.value.detail == "Greenhouse job data request timed out"


def test_public_job_fetch_converts_invalid_json_to_clean_502(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_api.job_imports.urlopen",
        lambda request, timeout: FakeResponse(),
    )
    monkeypatch.setattr(
        "agent_api.job_imports.json.load",
        lambda response: (_ for _ in ()).throw(
            json.JSONDecodeError("secret raw payload", "not-json", 0)
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _fetch_greenhouse_json("boards/acme")

    assert exc.value.status_code == 502
    assert exc.value.detail == "Greenhouse returned invalid JSON"
    assert "secret" not in exc.value.detail
