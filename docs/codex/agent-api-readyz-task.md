# Codex task: Add Postgres readiness to agent-api

## Goal

Add Postgres connectivity to the existing FastAPI agent-api service.

Current endpoint:

GET /healthz
returns:
{"status":"ok","service":"agent-api"}

Add:

GET /readyz

Behavior:
- /healthz checks only that the app process is alive.
- /readyz checks that agent-api can connect to Postgres.
- Do not print or log database passwords.
- Do not hardcode secrets.
- Do not modify live cluster resources manually.
- All Kubernetes changes must be done through GitOps manifests.

## Required Python changes

Update or create:

apps/agent-api/src/agent_api/settings.py
apps/agent-api/src/agent_api/db.py
apps/agent-api/src/agent_api/main.py
apps/agent-api/tests/test_health.py

Add dependencies:

psycopg[binary]
pydantic-settings

## Expected environment variables

POSTGRES_HOST=postgres.karyaquest-data.svc.cluster.local
POSTGRES_PORT=5432
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD

POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD must come from a Kubernetes Secret in the karyaquest-services namespace.

## Kubernetes/GitOps changes

Update:

deploy/base/agent-api/deployment.yaml

Add env vars for Postgres connection.

Important:
Kubernetes secrets are namespace-scoped.
Do not reference secret/postgres-auth from karyaquest-data directly.
Create or reference an app-specific DB secret in karyaquest-services.

For MVP, use a SOPS/KSOPS-managed encrypted secret later.
For this task, create only manifests/placeholders if secret values are not available.

## Acceptance criteria

1. pytest apps/agent-api passes.
2. /healthz still returns:
   {"status":"ok","service":"agent-api"}
3. /readyz returns healthy only when DB connection succeeds.
4. No secrets are printed in logs, tests, or docs.
5. No plaintext secret values are committed.
