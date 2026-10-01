"""Rutas HTTP para crear trabajos de transcripción."""

from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from app.api.dependencies import get_settings, require_service_token
from app.core.config import Settings
from app.models.transcriptions import (
    CreateTranscriptionRequest,
    TranscriptionJobResponse,
)
from app.services.duration import VideoDurationProbe, YtDlpVideoDurationProbe
from app.services.processor_factory import create_local_processor
from app.services.source_validation import (
    SourceNotAllowedError,
    validate_allowed_source,
)
from app.storage.jobs import SqliteJobStore, StoredJob
from app.workers.job_worker import JobWorker
from app.workers.runner import BoundedJobRunner

router = APIRouter(prefix="/v1/transcriptions", tags=["transcriptions"])


def get_job_store(request: Request) -> SqliteJobStore:
    """Obtiene el almacén asociado a la instancia FastAPI."""
    return request.app.state.job_store


def get_job_worker(
    request: Request,
    settings: Settings = Depends(get_settings),
    job_store: SqliteJobStore = Depends(get_job_store),
) -> JobWorker:
    """Crea una única instancia local del worker por proceso FastAPI."""
    worker = getattr(request.app.state, "job_worker", None)
    if worker is None:
        worker = JobWorker(
            job_store,
            create_local_processor(
                settings.model_path,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            ),
            settings.result_ttl_seconds,
        )
        request.app.state.job_worker = worker
    return worker


def get_video_duration_probe() -> VideoDurationProbe:
    """Obtiene la sonda local de metadatos usada antes de encolar trabajo."""
    return YtDlpVideoDurationProbe()


def get_job_runner(
    request: Request,
    settings: Settings = Depends(get_settings),
    worker: JobWorker = Depends(get_job_worker),
) -> BoundedJobRunner:
    """Devuelve el ejecutor local limitado para esta instancia de la API."""
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        runner = BoundedJobRunner(worker, settings.max_concurrent_jobs)
        request.app.state.job_runner = runner
    return runner


@router.get(
    "/{job_id}",
    response_model=TranscriptionJobResponse,
    dependencies=[Depends(require_service_token)],
)
def get_transcription(
    job_id: str,
    job_store: SqliteJobStore = Depends(get_job_store),
) -> TranscriptionJobResponse:
    """Devuelve el estado actual de un trabajo existente."""
    job_store.expire_due_results(datetime.now(UTC))
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Trabajo de transcripción no encontrado.",
        )
    return _to_response(job)


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_service_token)],
)
def delete_transcription(
    job_id: str,
    job_store: SqliteJobStore = Depends(get_job_store),
) -> Response:
    """Elimina un trabajo y permite tratar su cancelación como idempotente."""
    job_store.delete(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "",
    response_model=TranscriptionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_service_token)],
)
def create_transcription(
    payload: CreateTranscriptionRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    job_store: SqliteJobStore = Depends(get_job_store),
    duration_probe: VideoDurationProbe = Depends(get_video_duration_probe),
    runner: BoundedJobRunner = Depends(get_job_runner),
) -> TranscriptionJobResponse:
    """Registra un trabajo validado para su ejecución posterior."""
    try:
        validate_allowed_source(payload.source.url, settings.allowed_domain_set)
    except SourceNotAllowedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    duration = duration_probe.get_duration_seconds(str(payload.source.url))
    if duration is None:
        raise HTTPException(
            status_code=400,
            detail="No hemos podido determinar la duración del vídeo.",
        )
    if duration > settings.max_duration_seconds:
        raise HTTPException(
            status_code=400,
            detail="El vídeo supera el límite de duración para importar.",
        )

    job = job_store.create(str(payload.source.url), payload.language)
    background_tasks.add_task(runner.run_pending)
    return _to_response(job)


def _to_response(job: StoredJob) -> TranscriptionJobResponse:
    return TranscriptionJobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        language=job.language,
        duration_seconds=job.duration_seconds,
        text=job.text,
        segments=job.segments,
        expires_at=job.expires_at,
    )
