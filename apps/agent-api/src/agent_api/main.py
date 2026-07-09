from fastapi import FastAPI

app = FastAPI(title="KaryaQuest Agent API")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "agent-api"}
