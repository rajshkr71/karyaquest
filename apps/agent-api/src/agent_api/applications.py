from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_api.db import (
    create_application,
    get_application,
    list_applications,
    update_application,
)
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplicationCreate(BaseModel):
    job_id: UUID
    status: str = Field(default="draft", min_length=1)
    application_url: str | None = None
    submitted_at: datetime | None = None
    failure_reason: str | None = None
    manual_required_reason: str | None = None
    resume_document_id: UUID | None = None
    cover_letter_document_id: UUID | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = Field(default=None, min_length=1)
    application_url: str | None = None
    submitted_at: datetime | None = None
    failure_reason: str | None = None
    manual_required_reason: str | None = None
    resume_document_id: UUID | None = None
    cover_letter_document_id: UUID | None = None

    @field_validator("status")
    @classmethod
    def reject_null_status(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class Application(ApplicationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="application not found",
    )


@router.post("", response_model=Application, status_code=status.HTTP_201_CREATED)
def create(
    payload: ApplicationCreate,
    settings: Settings = Depends(get_settings),
) -> Application:
    return create_application(settings, payload.model_dump())


@router.get("", response_model=list[Application])
def list_all(settings: Settings = Depends(get_settings)) -> list[Application]:
    return list_applications(settings)


@router.get("/{application_id}", response_model=Application)
def get(
    application_id: UUID,
    settings: Settings = Depends(get_settings),
) -> Application:
    application = get_application(settings, application_id)
    if application is None:
        raise _not_found()
    return application


@router.patch("/{application_id}", response_model=Application)
def update(
    application_id: UUID,
    payload: ApplicationUpdate,
    settings: Settings = Depends(get_settings),
) -> Application:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one field is required",
        )

    application = update_application(settings, application_id, values)
    if application is None:
        raise _not_found()
    return application
