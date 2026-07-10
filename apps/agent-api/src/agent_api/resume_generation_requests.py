from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_api.db import (
    ActiveResumeGenerationRequestExists,
    InvalidResumeGenerationRequestTransition,
    ResumeGenerationApprovalMissing,
    create_resume_generation_request,
    get_resume_generation_request,
    list_resume_generation_requests,
    transition_resume_generation_request,
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
    processing_started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ResumeGenerationRequestFailure(BaseModel):
    failure_reason: str = Field(min_length=1)

    @field_validator("failure_reason")
    @classmethod
    def trim_and_reject_blank(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("failure_reason cannot be blank")
        return reason


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="resume generation request not found",
    )


def _transition(
    request_id: UUID,
    new_status: str,
    settings: Settings,
    failure_reason: str | None = None,
) -> ResumeGenerationRequest:
    try:
        request = transition_resume_generation_request(
            settings,
            request_id,
            new_status,
            failure_reason,
        )
    except InvalidResumeGenerationRequestTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invalid resume generation request transition",
        ) from exc

    if request is None:
        raise _not_found()
    return request


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


@router.post(
    "/resume-generation-requests/{request_id}/start",
    response_model=ResumeGenerationRequest,
)
def start(
    request_id: UUID,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationRequest:
    return _transition(request_id, "processing", settings)


@router.post(
    "/resume-generation-requests/{request_id}/complete",
    response_model=ResumeGenerationRequest,
)
def complete(
    request_id: UUID,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationRequest:
    return _transition(request_id, "completed", settings)


@router.post(
    "/resume-generation-requests/{request_id}/fail",
    response_model=ResumeGenerationRequest,
)
def fail(
    request_id: UUID,
    payload: ResumeGenerationRequestFailure,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationRequest:
    return _transition(request_id, "failed", settings, payload.failure_reason)
