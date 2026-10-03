"""Modelos públicos para trabajos de transcripción."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class SourceType(StrEnum):
    URL = "url"
    FILE = "file"


class TranscriptionSource(BaseModel):
    type: Literal["url"]
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def requires_https(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if url.scheme != "https":
            raise ValueError("La URL debe usar HTTPS.")
        return url


class CreateTranscriptionRequest(BaseModel):
    source: TranscriptionSource
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    groq_api_key: str | None = Field(default=None, alias="groqApiKey")


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1)

    @field_validator("end")
    @classmethod
    def ends_after_start(cls, end: float, info: object) -> float:
        start = getattr(info, "data", {}).get("start")
        if start is not None and end <= start:
            raise ValueError("El final debe ser posterior al inicio.")
        return end


class TranscriptionJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^trn_[A-Za-z0-9_-]+$")
    status: JobStatus
    created_at: datetime = Field(serialization_alias="createdAt")
    language: str | None = None
    duration_seconds: float | None = Field(
        default=None, ge=0, serialization_alias="durationSeconds"
    )
    text: str | None = None
    segments: list[Segment] | None = None
    expires_at: datetime | None = Field(default=None, serialization_alias="expiresAt")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")


class TranscriptionMetricsResponse(BaseModel):
    """Agregados operativos sin datos de fuentes ni transcripciones."""

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    queued_jobs: int = Field(ge=0, serialization_alias="queuedJobs")
    active_jobs: int = Field(ge=0, serialization_alias="activeJobs")
    completed_jobs: int = Field(ge=0, serialization_alias="completedJobs")
    failed_jobs: int = Field(ge=0, serialization_alias="failedJobs")
    average_completed_duration_seconds: float | None = Field(
        default=None,
        ge=0,
        serialization_alias="averageCompletedDurationSeconds",
    )
