"""Rutas HTTP para crear trabajos de transcripción."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.dependencies import get_settings, require_service_token
from app.core.config import Settings
from app.core.rate_limit import TokenRateLimiter
from app.models.transcriptions import (
    CreateTranscriptionRequest,
    SourceType,
    TranscriptionJobResponse,
    TranscriptionMetricsResponse,
)
from app.services.duration import (
    VideoDurationProbe,
    VideoMetadataError,
    YtDlpVideoDurationProbe,
)
from app.services.network_validation import (
    SourceHostResolutionError,
    UnsafeSourceHostError,
    validate_public_host,
)
from app.services.processor_factory import (
    create_groq_file_processor,
    create_groq_processor,
    create_local_file_processor,
    create_local_processor,
)
from app.services.redirect_validation import (
    UnsafeRedirectError,
    validate_redirect_chain,
)
from app.services.source_validation import (
    SourceNotAllowedError,
    validate_allowed_source,
)
from app.services.uploads import TemporaryUploadStore, UploadValidationError
from app.services.ytdlp import youtube_download_options
from app.storage.jobs import SqliteJobStore, StoredJob
from app.workers.job_worker import JobWorker
from app.workers.runner import BoundedJobRunner

router = APIRouter(prefix="/v1/transcriptions", tags=["transcriptions"])


def get_job_store(request: Request) -> SqliteJobStore:
    """Obtiene el almacén asociado a la instancia FastAPI."""
    return request.app.state.job_store


def get_upload_store(
    settings: Settings = Depends(get_settings),
) -> TemporaryUploadStore:
    """Crea el almacén temporal limitado para las subidas multipart."""
    return TemporaryUploadStore(settings.temporary_directory, settings.max_upload_bytes)


def get_job_worker(
    request: Request,
    settings: Settings = Depends(get_settings),
    job_store: SqliteJobStore = Depends(get_job_store),
) -> JobWorker:
    """Crea una única instancia local o de Groq del worker por proceso FastAPI."""
    worker = getattr(request.app.state, "job_worker", None)
    if worker is None:
        groq_key = (
            settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        )
        if groq_key:
            processor = create_groq_processor(
                groq_key,
                settings.groq_model,
                cookie_file=settings.youtube_cookie_file,
                download_options=youtube_download_options(settings),
            )
            file_processor = create_groq_file_processor(groq_key, settings.groq_model)
        else:
            processor = create_local_processor(
                settings.model_path,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                cookie_file=settings.youtube_cookie_file,
                download_options=youtube_download_options(settings),
            )
            file_processor = create_local_file_processor(
                settings.model_path,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        worker = JobWorker(
            job_store,
            processor,
            settings.result_ttl_seconds,
            file_processor,
        )
        request.app.state.job_worker = worker
    return worker


def get_video_duration_probe(
    settings: Settings = Depends(get_settings),
) -> VideoDurationProbe:
    """Obtiene la sonda local de metadatos usada antes de encolar trabajo."""
    return YtDlpVideoDurationProbe(
        cookie_file=settings.youtube_cookie_file,
        download_options=youtube_download_options(settings),
    )


def get_token_rate_limiter(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> TokenRateLimiter:
    """Mantiene el límite de trabajos por token durante la vida del proceso."""
    limiter = getattr(request.app.state, "token_rate_limiter", None)
    if limiter is None:
        limiter = TokenRateLimiter(
            settings.max_jobs_per_token,
            settings.rate_limit_window_seconds,
        )
        request.app.state.token_rate_limiter = limiter
    return limiter


def get_public_host_validator() -> Callable[[str], object]:
    """Expone la validación DNS como dependencia sustituible en pruebas."""
    return validate_public_host


def get_redirect_validator(
    host_validator: Callable[[str], object] = Depends(get_public_host_validator),
) -> Callable[[str], str]:
    """Compone la prevalidación de redirecciones con la validación DNS pública."""
    return lambda source_url: validate_redirect_chain(source_url, host_validator)


def get_job_runner(
    request: Request,
    settings: Settings = Depends(get_settings),
    worker: JobWorker = Depends(get_job_worker),
    job_store: SqliteJobStore = Depends(get_job_store),
) -> BoundedJobRunner | None:
    """Devuelve el ejecutor local limitado para esta instancia de la API."""
    if not settings.process_jobs_in_api:
        return None
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        job_store.requeue_stale_active_jobs(
            datetime.now(UTC)
            - timedelta(seconds=settings.stale_job_timeout_seconds)
        )
        runner = BoundedJobRunner(worker, settings.max_concurrent_jobs)
        request.app.state.job_runner = runner
    return runner


@router.get(
    "/metrics",
    response_model=TranscriptionMetricsResponse,
    dependencies=[Depends(require_service_token)],
)
def get_transcription_metrics(
    job_store: SqliteJobStore = Depends(get_job_store),
) -> TranscriptionMetricsResponse:
    """Expone agregados operativos sin contenido de trabajos."""
    return TranscriptionMetricsResponse.model_validate(job_store.metrics())


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
    job = job_store.get(job_id)
    job_store.delete(job_id)
    if job is not None and job.source_type is SourceType.FILE:
        Path(job.source_url).unlink(missing_ok=True)
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
    runner: BoundedJobRunner | None = Depends(get_job_runner),
    token_id: str = Depends(require_service_token),
    rate_limiter: TokenRateLimiter = Depends(get_token_rate_limiter),
    host_validator: Callable[[str], object] = Depends(get_public_host_validator),
    redirect_validator: Callable[[str], str] = Depends(get_redirect_validator),
) -> TranscriptionJobResponse:
    """Registra un trabajo validado para su ejecución posterior."""
    try:
        validate_allowed_source(payload.source.url, settings.allowed_domain_set)
    except SourceNotAllowedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        host_validator(payload.source.url.host)
    except (SourceHostResolutionError, UnsafeSourceHostError) as error:
        raise HTTPException(
            status_code=400,
            detail="No se ha podido validar el origen del vídeo.",
        ) from error

    try:
        source_url = redirect_validator(str(payload.source.url))
    except UnsafeRedirectError as error:
        raise HTTPException(
            status_code=400,
            detail="No se ha podido validar el origen del vídeo.",
        ) from error

    if not rate_limiter.allow(token_id):
        raise HTTPException(
            status_code=429,
            detail="Has alcanzado el límite de trabajos para este periodo.",
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )

    try:
        duration = duration_probe.get_duration_seconds(source_url)
    except VideoMetadataError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
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

    job = job_store.create(source_url, payload.language)
    if runner is not None:
        background_tasks.add_task(runner.run_pending)
    return _to_response(job)


@router.post(
    "/upload",
    response_model=TranscriptionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_service_token)],
)
def create_uploaded_transcription(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: str | None = Form(default=None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$"),
    settings: Settings = Depends(get_settings),
    job_store: SqliteJobStore = Depends(get_job_store),
    upload_store: TemporaryUploadStore = Depends(get_upload_store),
    runner: BoundedJobRunner | None = Depends(get_job_runner),
    token_id: str = Depends(require_service_token),
    rate_limiter: TokenRateLimiter = Depends(get_token_rate_limiter),
) -> TranscriptionJobResponse:
    """Guarda un audio o vídeo local y lo encola para Whisper local."""
    if not rate_limiter.allow(token_id):
        raise HTTPException(
            status_code=429,
            detail="Has alcanzado el límite de trabajos para este periodo.",
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )

    try:
        source_path = upload_store.save(file.file, file.filename or "")
    except UploadValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        job = job_store.create(str(source_path), language, source_type=SourceType.FILE)
    except Exception:
        source_path.unlink(missing_ok=True)
        raise

    if runner is not None:
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
        error_message=job.error_message,
    )
