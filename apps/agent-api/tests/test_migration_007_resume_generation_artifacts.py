import re
from pathlib import Path

import pytest


MIGRATION = Path(
    "deploy/base/postgres/migrations/007_resume_generation_artifacts.sql"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def migration_sql() -> str:
    return MIGRATION.read_text()


def valid_sha256(value: str) -> bool:
    return SHA256_PATTERN.fullmatch(value) is not None


def test_migration_007_defines_required_table_and_columns() -> None:
    sql = migration_sql()

    required_definitions = [
        "CREATE TABLE IF NOT EXISTS resume_generation_artifacts",
        "id UUID PRIMARY KEY",
        "request_id UUID NOT NULL UNIQUE",
        "job_id UUID NOT NULL",
        "source_resume_id UUID NOT NULL",
        "storage_bucket TEXT NOT NULL",
        "storage_key TEXT NOT NULL",
        "content_type TEXT NOT NULL",
        "sha256 TEXT NOT NULL",
        "size_bytes BIGINT NOT NULL",
        "provider TEXT NOT NULL",
        "model TEXT NOT NULL",
        "model_version TEXT NOT NULL",
        "input_tokens INTEGER NOT NULL",
        "output_tokens INTEGER NOT NULL",
        "latency_ms INTEGER NOT NULL",
        "finish_reason TEXT NOT NULL",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    ]

    assert all(definition in sql for definition in required_definitions)


def test_migration_007_defines_foreign_keys_and_constraints() -> None:
    sql = migration_sql()

    assert "REFERENCES resume_generation_requests(id)" in sql
    assert "REFERENCES jobs(id)" in sql
    assert "REFERENCES resumes(id)" in sql
    assert "UNIQUE (storage_bucket, storage_key)" in sql
    assert "size_bytes >= 0" in sql
    assert "input_tokens >= 0" in sql
    assert "output_tokens >= 0" in sql
    assert "latency_ms >= 0" in sql
    assert "sha256 ~ '^[0-9a-f]{64}$'" in sql


def test_sha256_rule_accepts_exactly_64_lowercase_hex_characters() -> None:
    assert valid_sha256("0123456789abcdef" * 4)


@pytest.mark.parametrize(
    "value",
    [
        "A" * 64,
        "g" * 64,
        "a" * 63,
        "a" * 65,
        "",
    ],
    ids=["uppercase", "non-hex", "too-short", "too-long", "blank"],
)
def test_sha256_rule_rejects_invalid_values(value: str) -> None:
    assert not valid_sha256(value)


def test_migration_007_contains_no_generated_content_columns() -> None:
    sql = migration_sql()
    column_names = set(
        re.findall(r"^\s{2}([a-z_]+)\s+[A-Z]+", sql, flags=re.MULTILINE)
    )

    assert column_names.isdisjoint(
        {"content", "resume_content", "generated_content", "prompt"}
    )
    assert "content_type" in column_names
