"""Obtención local de subtítulos mediante yt-dlp."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class SubtitleFetcher(Protocol):
    """Obtiene un archivo de subtítulos temporal para un origen de vídeo."""

    def fetch(
        self,
        source_url: str,
        language: str | None,
        temporary_directory: Path,
    ) -> Path | None: ...


class YoutubeDLContext(Protocol):
    def __enter__(self) -> "YoutubeDLContext": ...

    def __exit__(self, *args: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> dict[str, Any]: ...


class YtDlpSubtitleFetcher:
    """Pide subtítulos VTT sin descargar el vídeo ni su pista de audio."""

    def __init__(
        self,
        ydl_factory: Callable[[dict[str, Any]], YoutubeDLContext] | None = None,
    ) -> None:
        self._ydl_factory = ydl_factory

    def fetch(
        self,
        source_url: str,
        language: str | None,
        temporary_directory: Path,
    ) -> Path | None:
        temporary_directory.mkdir(parents=True, exist_ok=True)
        options = {
            "js_runtimes": {"deno": {}, "node": {}},
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [language or "es"],
            "subtitlesformat": "vtt",
            "outtmpl": str(temporary_directory / "%(id)s.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
        factory = self._ydl_factory or self._default_ydl_factory
        with factory(options) as ydl:
            ydl.extract_info(source_url, download=True)

        subtitle_files = sorted(temporary_directory.glob("*.vtt"))
        return subtitle_files[0] if subtitle_files else None

    @staticmethod
    def _default_ydl_factory(options: dict[str, Any]) -> YoutubeDLContext:
        from yt_dlp import YoutubeDL

        return YoutubeDL(options)
