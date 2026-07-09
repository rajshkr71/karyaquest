import logging

import psycopg
from psycopg.conninfo import make_conninfo

from agent_api.settings import Settings

logger = logging.getLogger(__name__)


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
