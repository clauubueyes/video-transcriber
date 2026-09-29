"""Punto de entrada HTTP de Video Transcriber."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Construye la aplicación sin iniciar trabajos ni cargar modelos."""
    app = FastAPI(
        title="Video Transcriber",
        version="0.1.0",
        description="Servicio autoalojable de transcripción local.",
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Informa que el proceso HTTP está disponible."""
        return {"status": "ok"}

    return app


app = create_app()
