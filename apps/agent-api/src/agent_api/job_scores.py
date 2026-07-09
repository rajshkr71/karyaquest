import re
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent_api.db import (
    create_job_score,
    get_job,
    get_job_score,
    get_resume,
    list_job_scores,
)
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/job-scores", tags=["job-scores"])
job_router = APIRouter(prefix="/jobs", tags=["job-scores"])


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


class MatchScoreCreate(BaseModel):
    resume_id: UUID


def _matches(skill: str, resume_content: str) -> bool:
    pattern = rf"(?<!\w){re.escape(skill.strip())}(?!\w)"
    return re.search(pattern, resume_content, flags=re.IGNORECASE) is not None


def _matched_and_missing(
    skills: list[Any],
    resume_content: str,
) -> tuple[list[str], list[str]]:
    matched = []
    missing = []
    seen = set()
    for value in skills:
        if not isinstance(value, str) or not value.strip():
            continue
        skill = value.strip()
        key = skill.casefold()
        if key in seen:
            continue
        seen.add(key)
        (matched if _matches(skill, resume_content) else missing).append(skill)
    return matched, missing


def calculate_match_score(
    required_skills: list[Any],
    preferred_skills: list[Any],
    resume_content: str,
) -> tuple[int, list[str], list[str]]:
    required_matches, required_gaps = _matched_and_missing(
        required_skills,
        resume_content,
    )
    preferred_matches, preferred_gaps = _matched_and_missing(
        preferred_skills,
        resume_content,
    )

    required_total = len(required_matches) + len(required_gaps)
    preferred_total = len(preferred_matches) + len(preferred_gaps)
    required_score = (
        70 * len(required_matches) / required_total if required_total else 0
    )
    preferred_score = (
        30 * len(preferred_matches) / preferred_total if preferred_total else 0
    )
    score = min(100, round(required_score + preferred_score))

    strengths = list(dict.fromkeys([*required_matches, *preferred_matches]))
    gaps = list(dict.fromkeys([*required_gaps, *preferred_gaps]))
    return score, strengths, gaps


def recommendation_for(score: int) -> str:
    if score >= 80:
        return "prepare_application"
    if score >= 60:
        return "review_required"
    return "reject"


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


@job_router.post(
    "/{job_id}/score",
    response_model=JobScore,
    status_code=status.HTTP_201_CREATED,
)
def score_job(
    job_id: UUID,
    payload: MatchScoreCreate,
    settings: Settings = Depends(get_settings),
) -> JobScore:
    job = get_job(settings, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )

    resume = get_resume(settings, payload.resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resume not found",
        )

    score, strengths, gaps = calculate_match_score(
        job["required_skills"],
        job["preferred_skills"],
        resume["content"],
    )
    return create_job_score(
        settings,
        {
            "job_id": job_id,
            "resume_id": payload.resume_id,
            "score": score,
            "strengths": strengths,
            "gaps": gaps,
            "recommendation": recommendation_for(score),
            "model_used": None,
        },
    )
