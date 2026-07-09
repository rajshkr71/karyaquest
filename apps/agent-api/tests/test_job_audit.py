from uuid import UUID

from agent_api import db

JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
JOB_SUMMARY = {
    "company": "Example Co",
    "title": "Python Developer",
    "source": "example",
}


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
        self.cursor_instance = FakeCursor(result)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.cursor_instance


def mock_database(monkeypatch, result):
    monkeypatch.setattr(db, "build_conninfo", lambda settings: "")
    monkeypatch.setattr(
        db.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(result),
    )


def test_create_job_writes_audit_row(monkeypatch) -> None:
    job = {"id": JOB_ID, **JOB_SUMMARY}
    audit = []
    mock_database(monkeypatch, job)
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, job_id, metadata: audit.append(
            (action, job_id, metadata)
        ),
    )

    db.create_job(object(), JOB_SUMMARY)

    assert audit == [("job.created", JOB_ID, JOB_SUMMARY)]


def test_update_job_writes_changed_fields_to_audit_row(monkeypatch) -> None:
    changed_fields = {"status": "reviewed", "salary_max": 140000}
    audit = []
    mock_database(monkeypatch, {"id": JOB_ID, **JOB_SUMMARY, **changed_fields})
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, job_id, metadata: audit.append(
            (action, job_id, metadata)
        ),
    )

    db.update_job(object(), JOB_ID, changed_fields)

    assert audit == [("job.updated", JOB_ID, changed_fields)]


def test_delete_job_writes_audit_row(monkeypatch) -> None:
    audit = []
    mock_database(monkeypatch, JOB_SUMMARY)
    monkeypatch.setattr(
        db,
        "_write_audit_log",
        lambda cur, action, job_id, metadata: audit.append(
            (action, job_id, metadata)
        ),
    )

    assert db.delete_job(object(), JOB_ID) is True
    assert audit == [("job.deleted", JOB_ID, JOB_SUMMARY)]
