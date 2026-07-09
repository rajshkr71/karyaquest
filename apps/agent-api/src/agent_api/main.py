from fastapi import Depends, FastAPI, HTTPException, status

from agent_api.applications import router as applications_router
from agent_api.db import check_postgres_ready, list_public_tables
from agent_api.generated_documents import router as generated_documents_router
from agent_api.jobs import router as jobs_router
from agent_api.profiles import router as profiles_router
from agent_api.resumes import router as resumes_router
from agent_api.settings import Settings, get_settings

app = FastAPI(title="KaryaQuest Agent API")
app.include_router(applications_router)
app.include_router(generated_documents_router)
app.include_router(jobs_router)
app.include_router(profiles_router)
app.include_router(resumes_router)


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


@app.get("/versionz")
def versionz(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    tables = list_public_tables(settings)

    if not tables:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database schema not visible",
        )

    return {
        "status": "ok",
        "database": "ready",
        "tables": tables,
    }
