import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg.conninfo import make_conninfo

from agent_api.settings import Settings

logger = logging.getLogger(__name__)

JOB_COLUMNS = """
    id, source, source_url, company, title, location, remote_type, description,
    required_skills, preferred_skills, salary_min, salary_max,
    detected_seniority, status, created_at, updated_at
"""


def _write_audit_log(
    cur: Any,
    action: str,
    job_id: UUID,
    metadata: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO audit_logs (actor, action, target_type, target_id, metadata)
        VALUES ('system', %s, 'job', %s, %s)
        """,
        (action, job_id, Jsonb(metadata)),
    )


def build_conninfo(settings: Settings) -> str:
    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=3,
    )


def check_postgres_ready(settings: Settings) -> bool:
    try:
        with psycopg.connect(build_conninfo(settings)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() == (1,)
    except Exception:
        logger.warning("Postgres readiness check failed")
        return False


def list_public_tables(settings: Settings) -> list[str]:
    try:
        with psycopg.connect(build_conninfo(settings)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                )
                return [row[0] for row in cur.fetchall()]
    except Exception:
        logger.warning("Postgres table visibility check failed")
        return []


def create_job(settings: Settings, values: dict[str, Any]) -> dict[str, Any]:
    columns = list(values)
    parameters = [
        Jsonb(value) if column.endswith("_skills") else value
        for column, value in values.items()
    ]
    placeholders = ", ".join(["%s"] * len(columns))

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO jobs ({", ".join(columns)})
                VALUES ({placeholders})
                RETURNING {JOB_COLUMNS}
                """,
                parameters,
            )
            job = cur.fetchone()
            _write_audit_log(
                cur,
                "job.created",
                job["id"],
                {
                    "company": job["company"],
                    "title": job["title"],
                    "source": job["source"],
                },
            )
            return job


def list_jobs(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {JOB_COLUMNS} FROM jobs ORDER BY created_at DESC")
            return cur.fetchall()


def get_job(settings: Settings, job_id: UUID) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s",
                (job_id,),
            )
            return cur.fetchone()


def update_job(
    settings: Settings,
    job_id: UUID,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    assignments = ", ".join(f"{column} = %s" for column in values)
    parameters = [
        Jsonb(value) if column.endswith("_skills") else value
        for column, value in values.items()
    ]

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE jobs
                SET {assignments}, updated_at = now()
                WHERE id = %s
                RETURNING {JOB_COLUMNS}
                """,
                [*parameters, job_id],
            )
            job = cur.fetchone()
            if job is not None:
                _write_audit_log(cur, "job.updated", job_id, values)
            return job


def delete_job(settings: Settings, job_id: UUID) -> bool:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM jobs
                WHERE id = %s
                RETURNING company, title, source
                """,
                (job_id,),
            )
            job = cur.fetchone()
            if job is None:
                return False
            _write_audit_log(cur, "job.deleted", job_id, job)
            return True
