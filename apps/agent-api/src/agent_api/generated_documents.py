from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from agent_api.db import (
    create_generated_document,
    get_generated_document,
    list_generated_documents,
)
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/generated-documents", tags=["generated-documents"])


class GeneratedDocumentCreate(BaseModel):
    job_id: UUID | None = None
    resume_id: UUID | None = None
    document_type: str = Field(min_length=1)
    storage_path: str = Field(min_length=1)
    checksum: str | None = None
    model_used: str | None = None


class GeneratedDocument(GeneratedDocumentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="generated document not found",
    )


@router.post(
    "",
    response_model=GeneratedDocument,
    status_code=status.HTTP_201_CREATED,
)
def create(
    payload: GeneratedDocumentCreate,
    settings: Settings = Depends(get_settings),
) -> GeneratedDocument:
    return create_generated_document(settings, payload.model_dump())


@router.get("", response_model=list[GeneratedDocument])
def list_all(
    settings: Settings = Depends(get_settings),
) -> list[GeneratedDocument]:
    return list_generated_documents(settings)


@router.get("/{document_id}", response_model=GeneratedDocument)
def get(
    document_id: UUID,
    settings: Settings = Depends(get_settings),
) -> GeneratedDocument:
    document = get_generated_document(settings, document_id)
    if document is None:
        raise _not_found()
    return document
