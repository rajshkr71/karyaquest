from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src"),
)

from resume_generator_worker.worker import ClaimConflict, run_once


CLAIM_TOKEN = "78cd0b26-b30a-4cf6-8c1e-031a0036fc45"
REQUEST_ID = "2ecee968-87dc-43bf-bf6b-10b5c4cfd379"


class FakeClient:
    def __init__(self, requests=None, claim_error=None):
        self.requests = requests or []
        self.claim_error = claim_error
        self.claims = []
        self.completed = []
        self.failed = []

    def list_requests(self):
        return self.requests

    def claim_request(self, request_id, worker_id):
        self.claims.append((request_id, worker_id))
        if self.claim_error:
            raise self.claim_error
        return {
            "id": request_id,
            "status": "processing",
            "claim_token": CLAIM_TOKEN,
        }

    def complete_request(self, request_id, claim_token):
        self.completed.append((request_id, claim_token))
        return {"id": request_id, "status": "completed"}

    def fail_request(self, request_id, claim_token, failure_reason):
        self.failed.append((request_id, claim_token, failure_reason))
        return {"id": request_id, "status": "failed"}


def queued_request():
    return {"id": REQUEST_ID, "status": "queued"}


def test_no_queued_request_exits_successfully(caplog):
    client = FakeClient([{"id": REQUEST_ID, "status": "processing"}])

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == 0
    assert client.claims == []
    assert "resume_generation.no_queued_request" in caplog.text


def test_successful_claim_and_complete():
    client = FakeClient([queued_request()])

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == 0
    assert client.claims == [(REQUEST_ID, "worker-a")]
    assert client.completed == [(REQUEST_ID, CLAIM_TOKEN)]
    assert client.failed == []


def test_claim_conflict_exits_safely():
    client = FakeClient([queued_request()], claim_error=ClaimConflict())

    exit_code = run_once(client, worker_id="worker-a")

    assert exit_code == 0
    assert client.claims == [(REQUEST_ID, "worker-a")]
    assert client.completed == []
    assert client.failed == []


def test_placeholder_failure_calls_fail():
    client = FakeClient([queued_request()])

    def fail_generation(request):
        raise RuntimeError("placeholder failed")

    exit_code = run_once(client, worker_id="worker-a", generator=fail_generation)

    assert exit_code == 1
    assert client.completed == []
    assert client.failed == [(REQUEST_ID, CLAIM_TOKEN, "placeholder failed")]


def test_claim_token_never_appears_in_logs(caplog):
    client = FakeClient([queued_request()])

    with caplog.at_level(logging.INFO, logger="resume_generator_worker"):
        run_once(client, worker_id="worker-a")

    assert CLAIM_TOKEN not in caplog.text
