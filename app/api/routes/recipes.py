"""Recetas desde trabajos públicos; conserva la autorización por trabajo."""

from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.routes.web import public_settings, read_public_job
from app.core.config import Settings
from app.core.rate_limit import TokenRateLimiter
from app.models.recipes import ExtractedRecipe
from app.models.transcriptions import JobStatus, TranscriptionJobResponse
from app.services.recipe_extractor import GroqRecipeExtractor, RecipeExtractionError
from app.storage.jobs import SqliteJobStore

router = APIRouter(tags=["recipes"])


def get_recipe_extractor(
    settings: Settings = Depends(public_settings),
) -> GroqRecipeExtractor:
    key = settings.recipe_api_key or settings.groq_api_key
    if not key or not key.get_secret_value().strip():
        raise HTTPException(
            503, "Configura VIDEO_TRANSCRIBER_GROQ_API_KEY o "
            "VIDEO_TRANSCRIBER_RECIPE_API_KEY en el servidor para extraer recetas.",
        )
    return GroqRecipeExtractor(
        key.get_secret_value(), settings.recipe_model,
        timeout_seconds=settings.recipe_timeout_seconds,
        max_transcript_chars=settings.recipe_max_transcript_chars,
    )


@router.post("/web/jobs/{job_id}/recipe", response_model=ExtractedRecipe)
def extract_public_recipe(
    job_id: str,
    request: Request,
    response: Response,
    job: TranscriptionJobResponse = Depends(read_public_job),
    settings: Settings = Depends(public_settings),
) -> ExtractedRecipe:
    response.headers["Cache-Control"] = "no-store"
    if not settings.recipe_extraction_enabled:
        raise HTTPException(404, "La extracción de recetas está desactivada.")
    if job.status is not JobStatus.COMPLETED:
        raise HTTPException(
            409, "La transcripción debe estar completada para extraer la receta.",
        )
    store: SqliteJobStore = request.app.state.job_store
    cached = store.get_recipe(job_id)
    if cached is not None:
        return ExtractedRecipe.model_validate(cached)
    if not job.text or len(job.text) > settings.recipe_max_transcript_chars:
        raise HTTPException(
            422, "La transcripción está vacía o supera el límite de extracción.",
        )
    extractor = get_recipe_extractor(settings)
    with request.app.state.runtime_lock:
        if not hasattr(request.app.state, "recipe_gate"):
            request.app.state.recipe_gate = Lock()
            request.app.state.recipe_limiter = TokenRateLimiter(
                settings.recipe_jobs_per_hour, 3600,
            )
        gate = request.app.state.recipe_gate
        limiter = request.app.state.recipe_limiter
    if not gate.acquire(blocking=False):
        raise HTTPException(
            503, "Hay otra receta en preparación. Espera unos segundos "
            "y vuelve a intentarlo.",
            headers={"Retry-After": "5"},
        )
    try:
        cached = store.get_recipe(job_id)
        if cached is not None:
            return ExtractedRecipe.model_validate(cached)
        if not limiter.allow("recipes"):
            raise HTTPException(
                429, "Se ha alcanzado el límite de extracción de recetas. "
                "Inténtalo más tarde.",
                headers={"Retry-After": "60"},
            )
        try:
            recipe = extractor.extract(job.text)
        except RecipeExtractionError as error:
            raise HTTPException(error.status_code, str(error)) from None
        if not store.save_recipe(job_id, recipe.model_dump(by_alias=True)):
            raise HTTPException(409, "La transcripción ha caducado o se ha eliminado.")
        return recipe
    finally:
        gate.release()
