"""Interfaz pública: cada resultado requiere su propia clave de acceso."""

from collections.abc import Callable
from hashlib import sha256
from hmac import compare_digest, new
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse

from app.api.dependencies import get_settings
from app.api.routes.transcriptions import (
    create_transcription,
    create_uploaded_transcription,
    get_job_runner,
    get_job_store,
    get_public_host_validator,
    get_redirect_validator,
    get_token_rate_limiter,
    get_transcription,
    get_upload_store,
    get_video_duration_probe,
)
from app.core.config import Settings
from app.core.rate_limit import TokenRateLimiter
from app.models.transcriptions import (
    CreateTranscriptionRequest,
    TranscriptionJobResponse,
)
from app.services.duration import VideoDurationProbe
from app.services.uploads import TemporaryUploadStore
from app.storage.jobs import SqliteJobStore
from app.workers.runner import BoundedJobRunner

router = APIRouter(tags=["web"])
WEB_DIRECTORY = Path(__file__).resolve().parents[2] / "web"


def public_settings(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.public_web_enabled:
        raise HTTPException(404, "La interfaz pública está desactivada.")
    return settings


def access_key(job_id: str, settings: Settings) -> str:
    return new(
        settings.token.get_secret_value().encode(),
        f"public-job:{job_id}".encode(),
        sha256,
    ).hexdigest()


def check_public_quota(request: Request, settings: Settings) -> str:
    """Aplica la cuota compartida de la web antes de procesar la entrada."""
    global_limiter = getattr(request.app.state, "public_limiter", None)
    if global_limiter is None:
        global_limiter = TokenRateLimiter(settings.public_jobs_per_hour, 3600)
        request.app.state.public_limiter = global_limiter
    if not global_limiter.allow("public"):
        raise HTTPException(429, "Estamos ocupados. Inténtalo más tarde.")
    identity = request.client.host if request.client else "unknown"
    return f"web:{identity}"


@router.get("/", include_in_schema=False)
def web_home() -> FileResponse:
    return FileResponse(
        WEB_DIRECTORY / "index.html", headers={"Cache-Control": "no-store"}
    )


@router.post("/web/jobs", status_code=202)
def create_public_job(
    payload: CreateTranscriptionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    settings: Settings = Depends(public_settings),
    store: SqliteJobStore = Depends(get_job_store),
    probe: VideoDurationProbe = Depends(get_video_duration_probe),
    runner: BoundedJobRunner | None = Depends(get_job_runner),
    limiter: TokenRateLimiter = Depends(get_token_rate_limiter),
    host_validator: Callable[[str], object] = Depends(get_public_host_validator),
    redirect_validator: Callable[[str], str] = Depends(get_redirect_validator),
) -> dict:
    # Cuota global antes de cualquier operación de red costosa.
    identity = check_public_quota(request, settings)
    job = create_transcription(
        payload, background_tasks, settings, store, probe, runner,
        identity, limiter, host_validator, redirect_validator,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "job": job.model_dump(mode="json", by_alias=True),
        "accessKey": access_key(job.id, settings),
    }


@router.post("/web/jobs/upload", status_code=202)
def create_public_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    file: UploadFile = File(...),
    language: str | None = Form(default=None, pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$"),
    settings: Settings = Depends(public_settings),
    store: SqliteJobStore = Depends(get_job_store),
    upload_store: TemporaryUploadStore = Depends(get_upload_store),
    runner: BoundedJobRunner | None = Depends(get_job_runner),
    limiter: TokenRateLimiter = Depends(get_token_rate_limiter),
) -> dict:
    """Encola una subida pública sin exponer el token privado al navegador."""
    identity = check_public_quota(request, settings)
    job = create_uploaded_transcription(
        background_tasks, file, language, settings, store, upload_store,
        runner, identity, limiter,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "job": job.model_dump(mode="json", by_alias=True),
        "accessKey": access_key(job.id, settings),
    }


@router.get("/web/jobs/{job_id}", response_model=TranscriptionJobResponse)
def read_public_job(
    job_id: str,
    response: Response,
    x_job_key: str = Header(default=""),
    settings: Settings = Depends(public_settings),
    store: SqliteJobStore = Depends(get_job_store),
) -> TranscriptionJobResponse:
    if not compare_digest(x_job_key.encode(), access_key(job_id, settings).encode()):
        raise HTTPException(404, "Transcripción no encontrada.")
    response.headers["Cache-Control"] = "no-store"
    return get_transcription(job_id, store)
