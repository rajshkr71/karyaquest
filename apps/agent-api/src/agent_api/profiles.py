from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_api.db import create_profile, get_profile, list_profiles, update_profile
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    content: dict[str, Any] | None = None

    @field_validator("name", "content")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class Profile(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="profile not found",
    )


@router.post("", response_model=Profile, status_code=status.HTTP_201_CREATED)
def create(
    payload: ProfileCreate,
    settings: Settings = Depends(get_settings),
) -> Profile:
    return create_profile(settings, payload.model_dump())


@router.get("", response_model=list[Profile])
def list_all(settings: Settings = Depends(get_settings)) -> list[Profile]:
    return list_profiles(settings)


@router.get("/{profile_id}", response_model=Profile)
def get(
    profile_id: UUID,
    settings: Settings = Depends(get_settings),
) -> Profile:
    profile = get_profile(settings, profile_id)
    if profile is None:
        raise _not_found()
    return profile


@router.patch("/{profile_id}", response_model=Profile)
def update(
    profile_id: UUID,
    payload: ProfileUpdate,
    settings: Settings = Depends(get_settings),
) -> Profile:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one field is required",
        )

    profile = update_profile(settings, profile_id, values)
    if profile is None:
        raise _not_found()
    return profile
