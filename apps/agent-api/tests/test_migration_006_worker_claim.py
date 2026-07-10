from pathlib import Path
from uuid import uuid4

MIGRATION = Path(
    "deploy/base/postgres/migrations/006_resume_generation_worker_claim.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text()


def apply_006_backfill(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    migrated = []
    for row in rows:
        values = row.copy()
        if values["status"] in {"processing", "completed", "failed"}:
            values["worker_id"] = values["worker_id"] or "legacy-pre-claim"
            values["claim_token"] = values["claim_token"] or uuid4()
            values["attempt_count"] = (
                values["attempt_count"] if values["attempt_count"] > 0 else 1
            )
        migrated.append(values)
    return migrated


def lifecycle_constraint_accepts(row: dict[str, object]) -> bool:
    status = row["status"]
    failure_reason = row["failure_reason"]
    worker_id = row["worker_id"]
    attempt_count = row["attempt_count"]

    if attempt_count < 0:
        return False

    if status == "queued":
        return (
            row["processing_started_at"] is None
            and row["completed_at"] is None
            and row["failed_at"] is None
            and failure_reason is None
            and worker_id is None
            and row["claim_token"] is None
            and attempt_count == 0
        )

    has_claim = (
        row["processing_started_at"] is not None
        and worker_id is not None
        and worker_id.strip() != ""
        and row["claim_token"] is not None
        and attempt_count > 0
    )
    if status == "processing":
        return (
            has_claim
            and row["completed_at"] is None
            and row["failed_at"] is None
            and failure_reason is None
        )
    if status == "completed":
        return (
            has_claim
            and row["completed_at"] is not None
            and row["failed_at"] is None
            and failure_reason is None
        )
    if status == "failed":
        return (
            has_claim
            and row["completed_at"] is None
            and row["failed_at"] is not None
            and isinstance(failure_reason, str)
            and failure_reason.strip() != ""
        )
    return False


def legacy_rows() -> list[dict[str, object]]:
    return [
        {
            "status": "queued",
            "processing_started_at": None,
            "completed_at": None,
            "failed_at": None,
            "failure_reason": None,
            "worker_id": None,
            "claim_token": None,
            "attempt_count": 0,
        },
        {
            "status": "processing",
            "processing_started_at": "2026-07-10T12:00:00Z",
            "completed_at": None,
            "failed_at": None,
            "failure_reason": None,
            "worker_id": None,
            "claim_token": None,
            "attempt_count": 0,
        },
        {
            "status": "completed",
            "processing_started_at": "2026-07-10T12:00:00Z",
            "completed_at": "2026-07-10T12:05:00Z",
            "failed_at": None,
            "failure_reason": None,
            "worker_id": None,
            "claim_token": None,
            "attempt_count": 0,
        },
        {
            "status": "failed",
            "processing_started_at": "2026-07-10T12:00:00Z",
            "completed_at": None,
            "failed_at": "2026-07-10T12:05:00Z",
            "failure_reason": "worker error",
            "worker_id": None,
            "claim_token": None,
            "attempt_count": 0,
        },
    ]


def test_migration_006_contains_legacy_backfill_and_standalone_constraint() -> None:
    sql = migration_sql()

    assert "worker_id = COALESCE(worker_id, 'legacy-pre-claim')" in sql
    assert "claim_token = COALESCE(claim_token, gen_random_uuid())" in sql
    assert "ELSE 1" in sql
    assert "WHERE status IN ('processing', 'completed', 'failed')" in sql
    assert "resume_generation_requests_attempt_count_check" in sql
    assert "CHECK (attempt_count >= 0)" in sql


def test_migration_006_backfills_legacy_claim_metadata() -> None:
    queued, processing, completed, failed = apply_006_backfill(legacy_rows())
    legacy = [processing, completed, failed]

    assert queued["worker_id"] is None
    assert queued["claim_token"] is None
    assert queued["attempt_count"] == 0

    assert all(row["worker_id"] == "legacy-pre-claim" for row in legacy)
    assert all(row["claim_token"] is not None for row in legacy)
    assert len({row["claim_token"] for row in legacy}) == len(legacy)
    assert all(row["attempt_count"] == 1 for row in legacy)


def test_migration_006_lifecycle_constraint_accepts_migrated_rows() -> None:
    migrated = apply_006_backfill(legacy_rows())

    assert all(lifecycle_constraint_accepts(row) for row in migrated)
