from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from agent_api.db import (
    ActiveResumeGenerationRequestExists,
    ResumeGenerationApprovalMissing,
    create_resume_generation_request,
    get_resume_generation_request,
    list_resume_generation_requests,
)
from agent_api.settings import Settings, get_settings

router = APIRouter(tags=["resume-generation-requests"])


class ResumeGenerationRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    approval_id: UUID
    resume_id: UUID | None = None
    status: str
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="resume generation request not found",
    )


@router.post(
    "/jobs/{job_id}/resume-generation-requests",
    response_model=ResumeGenerationRequest,
    status_code=status.HTTP_201_CREATED,
)
def create_for_job(
    job_id: UUID,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationRequest:
    try:
        request = create_resume_generation_request(settings, job_id)
    except ResumeGenerationApprovalMissing as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="resume generation approval is required",
        ) from exc
    except ActiveResumeGenerationRequestExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an active resume generation request already exists",
        ) from exc

    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    return request


@router.get(
    "/resume-generation-requests",
    response_model=list[ResumeGenerationRequest],
)
def list_all(
    settings: Settings = Depends(get_settings),
) -> list[ResumeGenerationRequest]:
    return list_resume_generation_requests(settings)


@router.get(
    "/resume-generation-requests/{request_id}",
    response_model=ResumeGenerationRequest,
)
def get(
    request_id: UUID,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationRequest:
    request = get_resume_generation_request(settings, request_id)
    if request is None:
        raise _not_found()
    return request
