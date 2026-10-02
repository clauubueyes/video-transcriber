"""Punto de entrada HTTP de Video Transcriber."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from app.api.routes.transcriptions import router as transcriptions_router
from app.api.routes.web import router as web_router
from app.core.logging import configure_logging
from app.storage.jobs import SqliteJobStore


def create_app(database_path: str | Path = "data/transcriber.sqlite3") -> FastAPI:
    """Construye la aplicación sin iniciar trabajos ni cargar modelos."""
    configure_logging()
    app = FastAPI(
        title="Video Transcriber",
        version="0.1.0",
        description="Servicio autoalojable de transcripción local.",
    )
    app.state.job_store = SqliteJobStore(database_path)
    app.include_router(transcriptions_router)
    app.include_router(web_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Informa que el proceso HTTP está disponible."""
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    async def ready() -> dict[str, str]:
        """Confirma que la API y su persistencia local están disponibles."""
        if not app.state.job_store.is_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El almacenamiento de trabajos no está disponible.",
            )
        return {"status": "ready"}

    return app


app = create_app()
