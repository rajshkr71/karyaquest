from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from agent_api.db import (
    ResumeGenerationApprovalExists,
    approve_resume_generation,
    list_resume_generation_approvals,
)
from agent_api.settings import Settings, get_settings

router = APIRouter(tags=["resume-generation-approvals"])


class ResumeGenerationApproval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    approved_at: datetime
    created_at: datetime


@router.get(
    "/resume-generation-approvals",
    response_model=list[ResumeGenerationApproval],
)
def list_all(
    settings: Settings = Depends(get_settings),
) -> list[ResumeGenerationApproval]:
    return list_resume_generation_approvals(settings)


@router.post(
    "/jobs/{job_id}/resume-generation-approval",
    response_model=ResumeGenerationApproval,
    status_code=status.HTTP_201_CREATED,
)
def approve_resume_generation_for_job(
    job_id: UUID,
    settings: Settings = Depends(get_settings),
) -> ResumeGenerationApproval:
    try:
        approval = approve_resume_generation(settings, job_id)
    except ResumeGenerationApprovalExists as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="resume generation approval already granted",
        ) from exc

    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    return approval
