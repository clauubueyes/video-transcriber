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


class ProcessingMethod(StrEnum):
    SUBTITLES = "subtitles"
    WHISPER_LOCAL = "whisper_local"
    GROQ = "groq"


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


class Chapter(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    title: str = Field(min_length=1)

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
    processing_seconds: float | None = Field(
        default=None, ge=0, serialization_alias="processingSeconds"
    )
    processing_method: ProcessingMethod | None = Field(
        default=None, serialization_alias="processingMethod"
    )
    processing_speed: float | None = Field(
        default=None, gt=0, serialization_alias="processingSpeed"
    )
    text: str | None = None
    segments: list[Segment] | None = None
    chapters: list[Chapter] | None = None
    expires_at: datetime | None = Field(default=None, serialization_alias="expiresAt")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")


class MethodPerformanceResponse(BaseModel):
    """Rendimiento de trabajos completados que usan el mismo método."""

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    method: ProcessingMethod | None = None
    completed_jobs: int = Field(ge=0, serialization_alias="completedJobs")
    measured_jobs: int = Field(ge=0, serialization_alias="measuredJobs")
    average_processing_seconds: float | None = Field(
        default=None, ge=0, serialization_alias="averageProcessingSeconds"
    )
    processing_speed: float | None = Field(
        default=None, gt=0, serialization_alias="processingSpeed"
    )


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
    performance_by_method: list[MethodPerformanceResponse] = Field(
        default_factory=list, serialization_alias="performanceByMethod"
    )
