"""Consulta de duración de vídeo antes de crear un trabajo costoso."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from yt_dlp.utils import DownloadError

from app.services.youtube_metadata import YoutubeMetadataCache, extract_with_metadata
from app.services.ytdlp import youtube_dl

logger = logging.getLogger("video_transcriber.duration")


def _provider_error_message(error: DownloadError) -> str:
    """Clasifica el fallo sin enviar detalles internos del proveedor al cliente."""
    detail = str(error).lower().replace("’", "'")
    if "confirm you're not a bot" in detail:
        return (
            "YouTube exige verificar que el servidor no es un bot. "
            "Limpiar la caché no resuelve este bloqueo. "
            "Utiliza Subir Archivo Audio/Vídeo o ejecuta el servicio localmente."
        )
    if any(marker in detail for marker in (
        "private video", "video unavailable", "video has been removed",
        "not available in your country", "sign in to confirm your age",
    )):
        return (
            "El vídeo no está disponible para el servidor o requiere iniciar sesión. "
            "Prueba con un vídeo público o utiliza Subir Archivo Audio/Vídeo."
        )
    if any(marker in detail for marker in (
        "javascript runtime", "challenge solving", "signature extraction failed",
        "nsig extraction failed", "requested format is not available",
    )):
        return (
            "El servidor no ha podido obtener los formatos del vídeo. "
            "Revisa yt-dlp y el runtime JavaScript en el despliegue. "
            "Puedes utilizar Subir Archivo Audio/Vídeo."
        )
    if "429" in detail or "too many requests" in detail:
        return (
            "YouTube ha limitado temporalmente las solicitudes del servidor. "
            "Inténtalo más tarde o utiliza Subir Archivo Audio/Vídeo."
        )
    return (
        "No se han podido consultar los metadatos del vídeo desde el servidor. "
        "Revisa los logs del servidor para identificar la causa. "
        "Puedes utilizar Subir Archivo Audio/Vídeo."
    )


class VideoMetadataError(RuntimeError):
    """El proveedor no permite consultar los metadatos del vídeo."""


class YoutubeDLContext(Protocol):
    def __enter__(self) -> "YoutubeDLContext": ...

    def __exit__(self, *args: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> dict[str, Any]: ...

    def process_ie_result(
        self, info: dict[str, Any], download: bool,
    ) -> dict[str, Any]: ...


class VideoDurationProbe(Protocol):
    """Obtiene duración en segundos sin descargar el contenido audiovisual."""

    def get_duration_seconds(self, source_url: str) -> float | None: ...


class YtDlpVideoDurationProbe:
    """Consulta metadatos de yt-dlp sin iniciar descarga de audio ni vídeo."""

    def __init__(
        self,
        ydl_factory: Callable[[dict[str, Any]], YoutubeDLContext] | None = None,
        *,
        cookie_file: Path | None = None,
        download_options: dict[str, Any] | None = None,
        metadata_cache: YoutubeMetadataCache | None = None,
    ) -> None:
        self._ydl_factory = ydl_factory
        self._cookie_file = cookie_file
        self._download_options = download_options or {}
        self._metadata_cache = metadata_cache

    def get_duration_seconds(self, source_url: str) -> float | None:
        if self._metadata_cache is not None:
            metadata = self._metadata_cache.get(source_url)
            if metadata is not None:
                duration = metadata.get("duration")
                return float(duration) if duration is not None else None
        options = {
            **self._download_options,
            "js_runtimes": self._download_options.get(
                "js_runtimes", {"deno": {}, "node": {}},
            ),
            "skip_download": True,
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": False,
        }
        factory = self._ydl_factory or self._default_ydl_factory
        try:
            with factory(options) as ydl:
                metadata = extract_with_metadata(
                    ydl, source_url, download=False, cache=self._metadata_cache,
                )
        except DownloadError as error:
            logger.warning("video_metadata_failed", exc_info=True)
            raise VideoMetadataError(_provider_error_message(error)) from error

        duration = metadata.get("duration")
        return float(duration) if duration is not None else None

    def _default_ydl_factory(self, options: dict[str, Any]):
        return youtube_dl(options, self._cookie_file)
