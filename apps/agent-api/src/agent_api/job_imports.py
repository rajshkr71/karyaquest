import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.errors import UniqueViolation

from agent_api.db import create_manual_job, job_source_url_exists
from agent_api.jobs import Job
from agent_api.settings import Settings, get_settings

router = APIRouter(prefix="/job-imports", tags=["job-imports"])
PUBLIC_JOB_IMPORT_USER_AGENT = "KaryaQuest/1.0"


class ManualJobImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: str = Field(min_length=1)
    company: str | None = None
    title: str | None = None
    location: str | None = None
    remote_type: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None


class GreenhouseImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    board_token: str | None = None
    job_url: str | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "GreenhouseImport":
        if (self.board_token is None) == (self.job_url is None):
            raise ValueError("provide exactly one of board_token or job_url")
        return self


class LeverImport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_token: str | None = None
    posting_id: str | None = None
    posting_url: str | None = None

    @model_validator(mode="after")
    def require_single_posting_source(self) -> "LeverImport":
        has_token_source = self.company_token is not None or self.posting_id is not None
        if self.posting_url is not None and has_token_source:
            raise ValueError("provide either posting_url or company_token with posting_id")
        if self.posting_url is None and not (
            self.company_token is not None and self.posting_id is not None
        ):
            raise ValueError("provide posting_url or company_token with posting_id")
        return self


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if text := data.strip():
            self.parts.append(text)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _clean_skills(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def normalize_manual_job(payload: ManualJobImport) -> dict[str, Any]:
    company = _clean_text(payload.company)
    title = _clean_text(payload.title)
    description = _clean_text(payload.description)
    normalized = all((company, title, description))

    return {
        "source": "manual",
        "source_url": payload.source_url.strip(),
        "company": company or "Unknown company",
        "title": title or "Untitled position",
        "location": _clean_text(payload.location),
        "remote_type": _clean_text(payload.remote_type),
        "description": description or "Description not provided",
        "required_skills": _clean_skills(payload.required_skills),
        "preferred_skills": _clean_skills(payload.preferred_skills),
        "status": "normalized" if normalized else "needs_review",
    }


def _parse_greenhouse_source(payload: GreenhouseImport) -> tuple[str, int | None]:
    if payload.board_token is not None:
        token = payload.board_token
        job_id = None
    else:
        parsed = urlparse(payload.job_url or "")
        if parsed.scheme != "https" or parsed.hostname not in {
            "boards.greenhouse.io",
            "job-boards.greenhouse.io",
        }:
            raise ValueError("job_url must be a public Greenhouse job URL")
        match = re.fullmatch(r"/([^/]+)/jobs/(\d+)/?", parsed.path)
        if match is None:
            raise ValueError("job_url must include a board token and job ID")
        token, raw_job_id = match.groups()
        job_id = int(raw_job_id)

    if re.fullmatch(r"[A-Za-z0-9_-]+", token) is None:
        raise ValueError("invalid Greenhouse board token")
    return token, job_id


def _fetch_public_job_json(url: str, provider: str) -> Any:
    request = Request(
        url,
        headers={"User-Agent": PUBLIC_JOB_IMPORT_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{provider} job data request timed out",
        ) from exc
    except HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider} job data could not be fetched",
        ) from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"{provider} job data request timed out",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider} job data could not be fetched",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider} returned invalid JSON",
        ) from exc


def _fetch_greenhouse_json(path: str) -> dict[str, Any]:
    return _fetch_public_job_json(
        f"https://boards-api.greenhouse.io/v1/{path}",
        "Greenhouse",
    )


def _fetch_lever_json(path: str) -> dict[str, Any]:
    data = _fetch_public_job_json(f"https://api.lever.co/v0/{path}", "Lever")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Lever returned invalid job data",
        )
    return data


def _plain_text(content: str) -> str:
    parser = _TextExtractor()
    parser.feed(unescape(content))
    return " ".join(parser.parts)


def _normalize_greenhouse_job(
    job: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    description = _plain_text(str(job.get("content") or ""))
    source_url = str(job.get("absolute_url") or "").strip()
    title = str(job.get("title") or "").strip()
    location = job.get("location") or {}
    location_name = str(location.get("name") or "").strip() or None
    normalized = all((source_url, company, title, description))
    return {
        "source": "greenhouse",
        "source_url": source_url,
        "company": company or "Unknown company",
        "title": title or "Untitled position",
        "location": location_name,
        "remote_type": None,
        "description": description or "Description not provided",
        "required_skills": [],
        "preferred_skills": [],
        "status": "normalized" if normalized else "needs_review",
    }


def _parse_lever_source(payload: LeverImport) -> tuple[str, str, str | None]:
    if payload.posting_url is not None:
        parsed = urlparse(payload.posting_url)
        if parsed.scheme != "https" or parsed.hostname != "jobs.lever.co":
            raise ValueError("posting_url must be a public Lever posting URL")
        match = re.fullmatch(r"/([^/]+)/([^/]+)(?:/apply)?/?", parsed.path)
        if match is None:
            raise ValueError("posting_url must include a company token and posting ID")
        company_token, posting_id = match.groups()
        source_url = payload.posting_url
    else:
        company_token = payload.company_token or ""
        posting_id = payload.posting_id or ""
        source_url = None

    if re.fullmatch(r"[A-Za-z0-9_-]+", company_token) is None:
        raise ValueError("invalid Lever company token")
    if re.fullmatch(r"[A-Za-z0-9_-]+", posting_id) is None:
        raise ValueError("invalid Lever posting ID")
    return company_token, posting_id, source_url


def _normalize_lever_job(
    job: dict[str, Any],
    company_token: str,
    fallback_source_url: str | None,
) -> dict[str, Any]:
    categories = job.get("categories") or {}
    lists = job.get("lists") or []
    description_parts = [
        str(job.get("descriptionPlain") or job.get("description") or "")
    ]
    if isinstance(lists, list):
        for item in lists:
            if isinstance(item, dict):
                description_parts.append(str(item.get("content") or ""))
    description = _plain_text(" ".join(description_parts))
    source_url = str(
        job.get("hostedUrl") or job.get("applyUrl") or fallback_source_url or ""
    ).strip()
    title = str(job.get("text") or "").strip()
    location = str(categories.get("location") or "").strip() or None
    normalized = all((source_url, company_token, title, description))
    return {
        "source": "lever",
        "source_url": source_url,
        "company": company_token,
        "title": title or "Untitled position",
        "location": location,
        "remote_type": None,
        "description": description or "Description not provided",
        "required_skills": [],
        "preferred_skills": [],
        "status": "normalized" if normalized else "needs_review",
    }


@router.post(
    "/manual",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
)
def import_manual_job(
    payload: ManualJobImport,
    settings: Settings = Depends(get_settings),
) -> Job:
    try:
        return create_manual_job(settings, normalize_manual_job(payload))
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc


@router.post(
    "/lever",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
)
def import_lever_job(
    payload: LeverImport,
    settings: Settings = Depends(get_settings),
) -> Job:
    try:
        company_token, posting_id, source_url = _parse_lever_source(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    token = quote(company_token, safe="")
    posting = quote(posting_id, safe="")
    values = _normalize_lever_job(
        _fetch_lever_json(f"postings/{token}/{posting}"),
        company_token,
        source_url,
    )
    if not values["source_url"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Lever returned a job without a source URL",
        )
    if job_source_url_exists(settings, values["source"], values["source_url"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a Lever job with this source URL already exists",
        )

    try:
        return create_manual_job(settings, values)
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc


@router.post(
    "/greenhouse",
    response_model=list[Job],
    status_code=status.HTTP_201_CREATED,
)
def import_greenhouse_jobs(
    payload: GreenhouseImport,
    settings: Settings = Depends(get_settings),
) -> list[Job]:
    try:
        board_token, job_id = _parse_greenhouse_source(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    token = quote(board_token, safe="")
    board = _fetch_greenhouse_json(f"boards/{token}")
    company = str(board.get("name") or "").strip()
    if job_id is None:
        response = _fetch_greenhouse_json(f"boards/{token}/jobs?content=true")
        jobs = response.get("jobs")
        if not isinstance(jobs, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Greenhouse returned invalid job data",
            )
    else:
        jobs = [_fetch_greenhouse_json(f"boards/{token}/jobs/{job_id}")]

    values = [_normalize_greenhouse_job(job, company) for job in jobs]
    if any(not item["source_url"] for item in values):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Greenhouse returned a job without a source URL",
        )
    if any(
        job_source_url_exists(
            settings,
            item["source"],
            item["source_url"],
        )
        for item in values
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a Greenhouse job with this source URL already exists",
        )

    try:
        return [create_manual_job(settings, item) for item in values]
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a job with this source URL already exists",
        ) from exc
