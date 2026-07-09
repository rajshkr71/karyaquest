from fastapi import Depends, FastAPI, HTTPException, status

from agent_api.db import check_postgres_ready
from agent_api.settings import Settings, get_settings

app = FastAPI(title="KaryaQuest Agent API")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "agent-api"}


@app.get("/readyz")
def readyz(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    if not check_postgres_ready(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database not ready",
        )

    return {"status": "ok", "database": "ready"}
