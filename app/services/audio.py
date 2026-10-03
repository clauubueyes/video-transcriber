"""Obtención local de audio temporal mediante yt-dlp."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.services.ytdlp import youtube_dl


class AudioFetcher(Protocol):
    """Descarga una pista de audio en un directorio temporal controlado."""

    def fetch(self, source_url: str, temporary_directory: Path) -> Path: ...


class YoutubeDLContext(Protocol):
    def __enter__(self) -> "YoutubeDLContext": ...

    def __exit__(self, *args: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> dict[str, Any]: ...


class AudioNotFoundError(RuntimeError):
    """yt-dlp terminó sin dejar una pista de audio utilizable."""


class YtDlpAudioFetcher:
    """Descarga solo la mejor pista de audio disponible, sin convertirla."""

    _AUDIO_EXTENSIONS = frozenset(
        {"aac", "flac", "m4a", "mp3", "ogg", "opus", "wav", "webm"}
    )

    def __init__(
        self,
        ydl_factory: Callable[[dict[str, Any]], YoutubeDLContext] | None = None,
        *,
        cookie_file: Path | None = None,
    ) -> None:
        self._ydl_factory = ydl_factory
        self._cookie_file = cookie_file

    def fetch(self, source_url: str, temporary_directory: Path) -> Path:
        temporary_directory.mkdir(parents=True, exist_ok=True)
        options = {
            "js_runtimes": {"deno": {}, "node": {}},
            "format": "bestaudio/best",
            "noplaylist": True,
            "outtmpl": str(temporary_directory / "%(id)s.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
        factory = self._ydl_factory or self._default_ydl_factory
        with factory(options) as ydl:
            ydl.extract_info(source_url, download=True)

        audio_files = sorted(
            path
            for path in temporary_directory.iterdir()
            if path.is_file()
            and path.suffix.lower().lstrip(".") in self._AUDIO_EXTENSIONS
        )
        if not audio_files:
            raise AudioNotFoundError("No se ha podido obtener el audio del vídeo.")
        return audio_files[0]

    def _default_ydl_factory(self, options: dict[str, Any]):
        return youtube_dl(options, self._cookie_file)
