from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from psycopg.errors import UniqueViolation

from agent_api.db import create_manual_job
from agent_api.jobs import Job
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/job-imports", tags=["job-imports"])


class ManualJobImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: str = Field(min_length=1)
    company: str | None = None
    title: str | None = None
    location: str | None = None
    remote_type: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _clean_skills(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def normalize_manual_job(payload: ManualJobImport) -> dict[str, Any]:
    company = _clean_text(payload.company)
    title = _clean_text(payload.title)
    description = _clean_text(payload.description)
    normalized = all((company, title, description))

    return {
        "source": "manual",
        "source_url": payload.source_url.strip(),
        "company": company or "Unknown company",
        "title": title or "Untitled position",
        "location": _clean_text(payload.location),
        "remote_type": _clean_text(payload.remote_type),
        "description": description or "Description not provided",
        "required_skills": _clean_skills(payload.required_skills),
        "preferred_skills": _clean_skills(payload.preferred_skills),
        "status": "normalized" if normalized else "needs_review",
    }


@router.post(
    "/manual",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
)
def import_manual_job(
    payload: ManualJobImport,
    settings: Settings = Depends(get_settings),
) -> Job:
    try:
        return create_manual_job(settings, normalize_manual_job(payload))
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc
