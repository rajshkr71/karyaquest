"""Database connectivity helpers.

Codex should complete this using psycopg.
Do not log passwords or full connection strings.
"""

from agent_api.settings import Settings


def check_postgres_ready(settings: Settings) -> bool:
    """Return True when Postgres is reachable.

    TODO for Codex:
    - Use psycopg.connect.
    - Run SELECT 1.
    - Return True on success.
    - Return False or raise controlled exception on failure.
    - Never print secrets.
    """
    raise NotImplementedError
