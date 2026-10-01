"""Consulta de duración de vídeo antes de crear un trabajo costoso."""

from collections.abc import Callable
from typing import Any, Protocol


class YoutubeDLContext(Protocol):
    def __enter__(self) -> "YoutubeDLContext": ...

    def __exit__(self, *args: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> dict[str, Any]: ...


class VideoDurationProbe(Protocol):
    """Obtiene duración en segundos sin descargar el contenido audiovisual."""

    def get_duration_seconds(self, source_url: str) -> float | None: ...


class YtDlpVideoDurationProbe:
    """Consulta metadatos de yt-dlp sin iniciar descarga de audio ni vídeo."""

    def __init__(
        self,
        ydl_factory: Callable[[dict[str, Any]], YoutubeDLContext] | None = None,
    ) -> None:
        self._ydl_factory = ydl_factory

    def get_duration_seconds(self, source_url: str) -> float | None:
        options = {
            "skip_download": True,
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
        factory = self._ydl_factory or self._default_ydl_factory
        with factory(options) as ydl:
            metadata = ydl.extract_info(source_url, download=False)

        duration = metadata.get("duration")
        return float(duration) if duration is not None else None

    @staticmethod
    def _default_ydl_factory(options: dict[str, Any]) -> YoutubeDLContext:
        from yt_dlp import YoutubeDL

        return YoutubeDL(options)
