from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.errors import UniqueViolation

from agent_api.db import create_job, delete_job, get_job, list_jobs, update_job
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreate(BaseModel):
    source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str | None = None
    remote_type: str | None = None
    description: str = Field(min_length=1)
    required_skills: list[Any] = Field(default_factory=list)
    preferred_skills: list[Any] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    detected_seniority: str | None = None
    status: str = Field(default="discovered", min_length=1)


class JobUpdate(BaseModel):
    source: str | None = Field(default=None, min_length=1)
    source_url: str | None = Field(default=None, min_length=1)
    company: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    location: str | None = None
    remote_type: str | None = None
    description: str | None = Field(default=None, min_length=1)
    required_skills: list[Any] | None = None
    preferred_skills: list[Any] | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    detected_seniority: str | None = None
    status: str | None = Field(default=None, min_length=1)

    @field_validator(
        "source",
        "source_url",
        "company",
        "title",
        "description",
        "required_skills",
        "preferred_skills",
        "status",
    )
    @classmethod
    def reject_null_for_required_columns(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class Job(JobCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="job not found",
    )


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
def create(payload: JobCreate, settings: Settings = Depends(get_settings)) -> Job:
    try:
        return create_job(settings, payload.model_dump())
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc


@router.get("", response_model=list[Job])
def list_all(settings: Settings = Depends(get_settings)) -> list[Job]:
    return list_jobs(settings)


@router.get("/{job_id}", response_model=Job)
def get(job_id: UUID, settings: Settings = Depends(get_settings)) -> Job:
    job = get_job(settings, job_id)
    if job is None:
        raise _not_found()
    return job


@router.patch("/{job_id}", response_model=Job)
def update(
    job_id: UUID,
    payload: JobUpdate,
    settings: Settings = Depends(get_settings),
) -> Job:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one field is required",
        )

    try:
        job = update_job(settings, job_id, values)
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc

    if job is None:
        raise _not_found()
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(job_id: UUID, settings: Settings = Depends(get_settings)) -> Response:
    if not delete_job(settings, job_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
