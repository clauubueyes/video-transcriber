"""Configuración tipada cargada exclusivamente en el proceso servidor."""

from functools import cached_property
from pathlib import Path
from typing import Literal

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
    max_duration_seconds: int = Field(default=3600, ge=1)
    result_ttl_seconds: int = Field(default=86400, ge=1)
    max_concurrent_jobs: int = Field(default=1, ge=1)
    max_pending_jobs: int = Field(default=10, ge=1)
    database_path: Path = Path("data/transcriber.sqlite3")
    worker_poll_interval_seconds: float = Field(default=2, gt=0)
    stale_job_timeout_seconds: int = Field(default=7200, ge=1)
    process_jobs_in_api: bool = True
    public_web_enabled: bool = True
    public_jobs_per_hour: int = Field(default=30, ge=1)
    max_jobs_per_token: int = Field(default=10, ge=1)
    rate_limit_window_seconds: int = Field(default=3600, ge=1)
    max_upload_bytes: int = Field(default=500_000_000, ge=1)
    temporary_directory: Path = Path("tmp")
    orphan_upload_age_seconds: int = Field(default=3600, ge=0)
    model_path: Path = Path("models/whisper-small")
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_cpu_threads: int = Field(default=2, ge=1)
    whisper_beam_size: int = Field(default=5, ge=1)
    groq_api_key: SecretStr | None = None
    groq_model: str = "whisper-large-v3-turbo"
    groq_chunk_seconds: int = Field(default=600, ge=30, le=600)
    groq_timeout_seconds: int = Field(default=120, ge=1)
    recipe_extraction_enabled: bool = True
    recipe_api_key: SecretStr | None = None
    recipe_model: str = "openai/gpt-oss-20b"
    recipe_timeout_seconds: int = Field(default=90, ge=1, le=110)
    recipe_max_transcript_chars: int = Field(default=120_000, ge=1)
    recipe_jobs_per_hour: int = Field(default=30, ge=1)
    youtube_cookie_file: Path | None = None
    youtube_player_clients: str | None = None
    youtube_po_token_server_home: Path | None = None
    youtube_po_token_base_url: str | None = None
    youtube_proxy_url: SecretStr | None = None
    youtube_impersonate: str | None = None
    youtube_po_token_policy: Literal["auto", "always", "never"] = "auto"
    youtube_po_token_mode: Literal["http", "script"] = "http"
    youtube_js_runtimes: str | None = None
    youtube_warp_config: SecretStr | None = None

    @cached_property
    def allowed_domain_set(self) -> frozenset[str]:
        """Devuelve dominios normalizados, sin entradas vacías."""
        return frozenset(
            domain.strip().lower()
            for domain in self.allowed_domains.split(",")
            if domain.strip()
        )
