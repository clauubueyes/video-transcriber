"""Punto de entrada HTTP de Video Transcriber."""

from pathlib import Path

from fastapi import FastAPI

from app.api.routes.transcriptions import router as transcriptions_router
from app.storage.jobs import SqliteJobStore


def create_app(database_path: str | Path = "data/transcriber.sqlite3") -> FastAPI:
    """Construye la aplicación sin iniciar trabajos ni cargar modelos."""
    app = FastAPI(
        title="Video Transcriber",
        version="0.1.0",
        description="Servicio autoalojable de transcripción local.",
    )
    app.state.job_store = SqliteJobStore(database_path)
    app.include_router(transcriptions_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Informa que el proceso HTTP está disponible."""
        return {"status": "ok"}

    return app


app = create_app()
