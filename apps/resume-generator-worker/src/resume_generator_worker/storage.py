from __future__ import annotations

import hashlib
import json
import socket
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Protocol


class ArtifactStorageError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ArtifactStat:
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ArtifactMetadata:
    storage_bucket: str
    storage_key: str
    content_type: str
    sha256: str
    size_bytes: int
    provider: str
    model: str
    model_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    finish_reason: str


@dataclass(frozen=True)
class StoredArtifact:
    metadata: ArtifactMetadata
    created: bool


class ArtifactStore(Protocol):
    def stat(self, bucket: str, key: str) -> ArtifactStat | None: ...

    def create_only(
        self,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool: ...

    def remove(self, bucket: str, key: str) -> None: ...


def canonical_artifact_bytes(request: Any, result: Any) -> bytes:
    try:
        document = {
            "schema_version": 1,
            "request_id": request.request_id,
            "job_id": request.job_id,
            "source_resume_id": request.resume_id,
            **asdict(result),
        }
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception as exc:
        raise ArtifactStorageError("artifact_serialization_failed") from exc


def persist_artifact(
    store: ArtifactStore,
    request: Any,
    execution: Any,
    bucket: str,
) -> StoredArtifact:
    content = canonical_artifact_bytes(request, execution.result)
    checksum = hashlib.sha256(content).hexdigest()
    key = f"resume-generation/{request.request_id}/result.json"
    artifact = ArtifactMetadata(
        storage_bucket=bucket,
        storage_key=key,
        content_type="application/json",
        sha256=checksum,
        size_bytes=len(content),
        provider=execution.provider,
        model=execution.model,
        model_version=execution.model_version,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        latency_ms=execution.latency_ms,
        finish_reason=execution.finish_reason,
    )
    created = store.create_only(
        bucket,
        key,
        content,
        artifact.content_type,
        {
            "sha256": checksum,
            "request-id": request.request_id,
            "job-id": request.job_id,
            "source-resume-id": request.resume_id,
        },
    )
    existing = store.stat(bucket, key)
    if (
        existing is None
        or existing.sha256 != checksum
        or existing.size_bytes != len(content)
    ):
        raise ArtifactStorageError("artifact_storage_conflict")
    return StoredArtifact(artifact, created=created)


class MinioArtifactStore:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
    ) -> None:
        from minio import Minio

        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def stat(self, bucket: str, key: str) -> ArtifactStat | None:
        try:
            response = self.client.stat_object(bucket, key)
        except Exception as exc:
            if exc.__class__.__name__ == "S3Error" and getattr(
                exc, "code", ""
            ) in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return None
            raise self._safe_error(exc) from None
        metadata = {
            str(key).lower(): value
            for key, value in getattr(response, "metadata", {}).items()
        }
        checksum = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
        size = getattr(response, "size", None)
        if (
            not isinstance(checksum, str)
            or not re.fullmatch(r"[0-9a-f]{64}", checksum)
            or type(size) is not int
            or size < 0
        ):
            raise ArtifactStorageError("artifact_storage_invalid_response")
        return ArtifactStat(checksum, size)

    def create_only(
        self,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> bool:
        try:
            self._conditional_put(bucket, key, content, content_type, metadata)
        except Exception as exc:
            if self._is_precondition_failure(exc):
                return False
            raise self._safe_error(exc) from None
        return True

    def _conditional_put(
        self,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        # minio-py 7.2.20 put_object does not expose If-None-Match. _execute is
        # the SDK's signed request path, isolated here to keep create-only
        # semantics without ever falling back to an unconditional upload.
        headers = {
            "Content-Length": str(len(content)),
            "Content-Type": content_type,
            "If-None-Match": "*",
            **{f"X-Amz-Meta-{name}": value for name, value in metadata.items()},
        }
        self.client._execute(  # noqa: SLF001
            "PUT",
            bucket,
            key,
            body=BytesIO(content),
            headers=headers,
        )

    def remove(self, bucket: str, key: str) -> None:
        try:
            self.client.remove_object(bucket, key)
        except Exception as exc:
            raise self._safe_error(exc) from None

    @staticmethod
    def _is_precondition_failure(exc: Exception) -> bool:
        return (
            getattr(exc, "code", "")
            in {"PreconditionFailed", "ConditionalRequestConflict"}
            or getattr(exc, "status", None) in {409, 412}
            or getattr(exc, "status_code", None) in {409, 412}
        )

    @staticmethod
    def _safe_error(exc: Exception) -> ArtifactStorageError:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return ArtifactStorageError("artifact_storage_timeout")
        if exc.__class__.__name__ in {"InvalidResponseError", "ValueError"}:
            return ArtifactStorageError("artifact_storage_invalid_response")
        return ArtifactStorageError("artifact_storage_connection_error")


BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def validate_storage_configuration(
    endpoint: Any,
    access_key: Any,
    secret_key: Any,
    bucket: Any,
) -> tuple[str, str, str, str]:
    values = (endpoint, access_key, secret_key, bucket)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ArtifactStorageError("artifact_storage_configuration_error")
    endpoint, access_key, secret_key, bucket = (value.strip() for value in values)
    if any(character.isspace() for character in endpoint):
        raise ArtifactStorageError("artifact_storage_configuration_error")
    if (
        not BUCKET_PATTERN.fullmatch(bucket)
        or ".." in bucket
        or ".-" in bucket
        or "-." in bucket
        or re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", bucket)
    ):
        raise ArtifactStorageError("artifact_storage_configuration_error")
    return endpoint, access_key, secret_key, bucket
