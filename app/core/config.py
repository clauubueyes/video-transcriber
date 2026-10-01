"""Configuración tipada cargada exclusivamente en el proceso servidor."""

from functools import cached_property
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores de operación del servicio.

    El token no tiene valor por defecto: cada despliegue debe proporcionar
    ``VIDEO_TRANSCRIBER_TOKEN`` antes de habilitar rutas protegidas.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VIDEO_TRANSCRIBER_",
        extra="ignore",
    )

    token: SecretStr
    allowed_domains: str = "youtube.com,www.youtube.com,youtu.be"
    max_duration_seconds: int = Field(default=1800, ge=1)
    result_ttl_seconds: int = Field(default=86400, ge=1)
    max_concurrent_jobs: int = Field(default=1, ge=1)
    database_path: Path = Path("data/transcriber.sqlite3")
    worker_poll_interval_seconds: float = Field(default=2, gt=0)
    model_path: Path = Path("models/whisper-small")
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    @cached_property
    def allowed_domain_set(self) -> frozenset[str]:
        """Devuelve dominios normalizados, sin entradas vacías."""
        return frozenset(
            domain.strip().lower()
            for domain in self.allowed_domains.split(",")
            if domain.strip()
        )
