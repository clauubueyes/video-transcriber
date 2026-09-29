"""Rutas HTTP para crear trabajos de transcripción."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_settings, require_service_token
from app.core.config import Settings
from app.models.transcriptions import (
    CreateTranscriptionRequest,
    TranscriptionJobResponse,
)
from app.services.source_validation import (
    SourceNotAllowedError,
    validate_allowed_source,
)
from app.storage.jobs import SqliteJobStore, StoredJob

router = APIRouter(prefix="/v1/transcriptions", tags=["transcriptions"])


def get_job_store(request: Request) -> SqliteJobStore:
    """Obtiene el almacén asociado a la instancia FastAPI."""
    return request.app.state.job_store


@router.post(
    "",
    response_model=TranscriptionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_service_token)],
)
def create_transcription(
    payload: CreateTranscriptionRequest,
    settings: Settings = Depends(get_settings),
    job_store: SqliteJobStore = Depends(get_job_store),
) -> TranscriptionJobResponse:
    """Registra un trabajo validado para su ejecución posterior."""
    try:
        validate_allowed_source(payload.source.url, settings.allowed_domain_set)
    except SourceNotAllowedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    job = job_store.create(str(payload.source.url), payload.language)
    return _to_response(job)


def _to_response(job: StoredJob) -> TranscriptionJobResponse:
    return TranscriptionJobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        language=job.language,
    )
