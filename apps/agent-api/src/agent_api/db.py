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

APPLICATION_COLUMNS = """
    id, job_id, status, application_url, submitted_at, failure_reason,
    manual_required_reason, resume_document_id, cover_letter_document_id,
    created_at, updated_at
"""

PROFILE_COLUMNS = "id, name, content, created_at, updated_at"
RESUME_COLUMNS = (
    "id, name, base_profile_id, content, version, created_at, updated_at"
)
GENERATED_DOCUMENT_COLUMNS = """
    id, job_id, resume_id, document_type, storage_path, checksum, model_used,
    created_at
"""
JOB_SCORE_COLUMNS = """
    id, job_id, resume_id, score, strengths, gaps, recommendation, model_used,
    created_at
"""


def _write_audit_log(
    cur: Any,
    action: str,
    target_id: UUID,
    metadata: dict[str, Any],
    target_type: str = "job",
) -> None:
    cur.execute(
        """
        INSERT INTO audit_logs (actor, action, target_type, target_id, metadata)
        VALUES ('system', %s, %s, %s, %s)
        """,
        (action, target_type, target_id, Jsonb(metadata)),
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


def create_application(
    settings: Settings,
    values: dict[str, Any],
) -> dict[str, Any]:
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO applications ({", ".join(columns)})
                VALUES ({placeholders})
                RETURNING {APPLICATION_COLUMNS}
                """,
                list(values.values()),
            )
            return cur.fetchone()


def list_applications(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {APPLICATION_COLUMNS}
                FROM applications
                ORDER BY created_at DESC
                """
            )
            return cur.fetchall()


def get_application(
    settings: Settings,
    application_id: UUID,
) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {APPLICATION_COLUMNS} FROM applications WHERE id = %s",
                (application_id,),
            )
            return cur.fetchone()


def update_application(
    settings: Settings,
    application_id: UUID,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    assignments = ", ".join(f"{column} = %s" for column in values)

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM applications WHERE id = %s FOR UPDATE",
                (application_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                return None

            cur.execute(
                f"""
                UPDATE applications
                SET {assignments}, updated_at = now()
                WHERE id = %s
                RETURNING {APPLICATION_COLUMNS}
                """,
                [*values.values(), application_id],
            )
            application = cur.fetchone()
            old_status = existing["status"]
            new_status = application["status"]
            if new_status != old_status:
                _write_audit_log(
                    cur,
                    "application.status_changed",
                    application_id,
                    {"old_status": old_status, "new_status": new_status},
                    target_type="application",
                )
            return application


def create_profile(
    settings: Settings,
    values: dict[str, Any],
) -> dict[str, Any]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO profiles (name, content)
                VALUES (%s, %s)
                RETURNING {PROFILE_COLUMNS}
                """,
                (values["name"], Jsonb(values["content"])),
            )
            profile = cur.fetchone()
            _write_audit_log(
                cur,
                "profile.created",
                profile["id"],
                {"name": profile["name"]},
                target_type="profile",
            )
            return profile


def list_profiles(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PROFILE_COLUMNS} FROM profiles ORDER BY created_at DESC"
            )
            return cur.fetchall()


def get_profile(
    settings: Settings,
    profile_id: UUID,
) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PROFILE_COLUMNS} FROM profiles WHERE id = %s",
                (profile_id,),
            )
            return cur.fetchone()


def update_profile(
    settings: Settings,
    profile_id: UUID,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    assignments = ", ".join(f"{column} = %s" for column in values)
    parameters = [
        Jsonb(value) if column == "content" else value
        for column, value in values.items()
    ]

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE profiles
                SET {assignments}, updated_at = now()
                WHERE id = %s
                RETURNING {PROFILE_COLUMNS}
                """,
                [*parameters, profile_id],
            )
            profile = cur.fetchone()
            if profile is not None:
                _write_audit_log(
                    cur,
                    "profile.updated",
                    profile_id,
                    {"changed_fields": list(values)},
                    target_type="profile",
                )
            return profile


def create_resume(
    settings: Settings,
    values: dict[str, Any],
) -> dict[str, Any]:
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO resumes ({", ".join(columns)})
                VALUES ({placeholders})
                RETURNING {RESUME_COLUMNS}
                """,
                list(values.values()),
            )
            resume = cur.fetchone()
            _write_audit_log(
                cur,
                "resume.created",
                resume["id"],
                {
                    "name": resume["name"],
                    "base_profile_id": (
                        str(resume["base_profile_id"])
                        if resume["base_profile_id"] is not None
                        else None
                    ),
                    "version": resume["version"],
                },
                target_type="resume",
            )
            return resume


def list_resumes(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {RESUME_COLUMNS} FROM resumes ORDER BY created_at DESC"
            )
            return cur.fetchall()


def get_resume(
    settings: Settings,
    resume_id: UUID,
) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {RESUME_COLUMNS} FROM resumes WHERE id = %s",
                (resume_id,),
            )
            return cur.fetchone()


def create_generated_document(
    settings: Settings,
    values: dict[str, Any],
) -> dict[str, Any]:
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO generated_documents ({", ".join(columns)})
                VALUES ({placeholders})
                RETURNING {GENERATED_DOCUMENT_COLUMNS}
                """,
                list(values.values()),
            )
            document = cur.fetchone()
            _write_audit_log(
                cur,
                "generated_document.created",
                document["id"],
                {
                    "document_type": document["document_type"],
                    "job_id": (
                        str(document["job_id"])
                        if document["job_id"] is not None
                        else None
                    ),
                    "resume_id": (
                        str(document["resume_id"])
                        if document["resume_id"] is not None
                        else None
                    ),
                    "checksum": document["checksum"],
                },
                target_type="generated_document",
            )
            return document


def list_generated_documents(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {GENERATED_DOCUMENT_COLUMNS}
                FROM generated_documents
                ORDER BY created_at DESC
                """
            )
            return cur.fetchall()


def get_generated_document(
    settings: Settings,
    document_id: UUID,
) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {GENERATED_DOCUMENT_COLUMNS}
                FROM generated_documents
                WHERE id = %s
                """,
                (document_id,),
            )
            return cur.fetchone()


def create_job_score(
    settings: Settings,
    values: dict[str, Any],
) -> dict[str, Any]:
    columns = list(values)
    parameters = [
        Jsonb(value) if column in {"strengths", "gaps"} else value
        for column, value in values.items()
    ]
    placeholders = ", ".join(["%s"] * len(columns))

    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO job_scores ({", ".join(columns)})
                VALUES ({placeholders})
                RETURNING {JOB_SCORE_COLUMNS}
                """,
                parameters,
            )
            job_score = cur.fetchone()
            _write_audit_log(
                cur,
                "job.scored",
                job_score["job_id"],
                {
                    "job_id": str(job_score["job_id"]),
                    "resume_id": (
                        str(job_score["resume_id"])
                        if job_score["resume_id"] is not None
                        else None
                    ),
                    "score": job_score["score"],
                    "recommendation": job_score["recommendation"],
                    "model_used": job_score["model_used"],
                },
            )
            return job_score


def list_job_scores(settings: Settings) -> list[dict[str, Any]]:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {JOB_SCORE_COLUMNS}
                FROM job_scores
                ORDER BY created_at DESC
                """
            )
            return cur.fetchall()


def get_job_score(
    settings: Settings,
    score_id: UUID,
) -> dict[str, Any] | None:
    with psycopg.connect(build_conninfo(settings), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {JOB_SCORE_COLUMNS} FROM job_scores WHERE id = %s",
                (score_id,),
            )
            return cur.fetchone()
