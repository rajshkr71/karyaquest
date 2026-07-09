from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent_api.db import create_job_score, get_job_score, list_job_scores
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/job-scores", tags=["job-scores"])


class JobScoreCreate(BaseModel):
    job_id: UUID
    resume_id: UUID | None = None
    score: int = Field(ge=0, le=100)
    strengths: list[Any] = Field(default_factory=list)
    gaps: list[Any] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)
    model_used: str | None = None


class JobScore(JobScoreCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="job score not found",
    )


@router.post("", response_model=JobScore, status_code=status.HTTP_201_CREATED)
def create(
    payload: JobScoreCreate,
    settings: Settings = Depends(get_settings),
) -> JobScore:
    return create_job_score(settings, payload.model_dump())


@router.get("", response_model=list[JobScore])
def list_all(settings: Settings = Depends(get_settings)) -> list[JobScore]:
    return list_job_scores(settings)


@router.get("/{score_id}", response_model=JobScore)
def get(
    score_id: UUID,
    settings: Settings = Depends(get_settings),
) -> JobScore:
    job_score = get_job_score(settings, score_id)
    if job_score is None:
        raise _not_found()
    return job_score
