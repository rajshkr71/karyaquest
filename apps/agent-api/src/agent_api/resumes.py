from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent_api.db import create_resume, get_resume, list_resumes
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/resumes", tags=["resumes"])


class ResumeCreate(BaseModel):
    name: str = Field(min_length=1)
    base_profile_id: UUID | None = None
    content: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)


class Resume(ResumeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="resume not found",
    )


@router.post("", response_model=Resume, status_code=status.HTTP_201_CREATED)
def create(
    payload: ResumeCreate,
    settings: Settings = Depends(get_settings),
) -> Resume:
    return create_resume(settings, payload.model_dump())


@router.get("", response_model=list[Resume])
def list_all(settings: Settings = Depends(get_settings)) -> list[Resume]:
    return list_resumes(settings)


@router.get("/{resume_id}", response_model=Resume)
def get(
    resume_id: UUID,
    settings: Settings = Depends(get_settings),
) -> Resume:
    resume = get_resume(settings, resume_id)
    if resume is None:
        raise _not_found()
    return resume
