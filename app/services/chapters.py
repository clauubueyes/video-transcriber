"""Capítulos del vídeo reutilizando la extracción de metadatos de yt-dlp."""

from collections.abc import Callable
from math import isfinite
from pathlib import Path
from typing import Any, Protocol

from app.models.transcriptions import Chapter
from app.services.youtube_metadata import YoutubeMetadataCache, extract_with_metadata
from app.services.ytdlp import youtube_dl


class ChapterFetcher(Protocol):
    def fetch(self, source_url: str) -> list[Chapter]: ...


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) and value >= 0 else None


def parse_chapters(metadata: dict[str, Any]) -> list[Chapter]:
    """Ignora entradas inválidas y acota cada capítulo al inicio del siguiente."""
    raw_chapters = metadata.get("chapters")
    if not isinstance(raw_chapters, list):
        return []
    duration = _seconds(metadata.get("duration"))
    entries: dict[float, tuple[str, float | None]] = {}
    for raw in raw_chapters:
        if not isinstance(raw, dict):
            continue
        start = _seconds(raw.get("start_time"))
        title = raw.get("title")
        if start is None or not isinstance(title, str) or not title.strip():
            continue
        if duration is not None and start >= duration:
            continue
        end = _seconds(raw.get("end_time"))
        if end is not None and end <= start:
            continue
        entries.setdefault(start, (" ".join(title.split()), end))

    starts = sorted(entries)
    chapters = []
    for index, start in enumerate(starts):
        title, end = entries[start]
        limits = [value for value in (end, duration) if value is not None]
        if index + 1 < len(starts):
            limits.append(starts[index + 1])
        if limits and min(limits) > start:
            chapters.append(Chapter(start=start, end=min(limits), title=title))
    return chapters


class YtDlpChapterFetcher:
    """Lee los capítulos antes de transcribir, sin descargar audio adicional."""

    def __init__(
        self,
        *,
        metadata_cache: YoutubeMetadataCache,
        cookie_file: Path | None = None,
        download_options: dict[str, Any] | None = None,
        ydl_factory: Callable | None = None,
    ) -> None:
        self._metadata_cache = metadata_cache
        self._cookie_file = cookie_file
        self._download_options = download_options or {}
        self._ydl_factory = ydl_factory

    def fetch(self, source_url: str) -> list[Chapter]:
        metadata = self._metadata_cache.get(source_url)
        if metadata is None:
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
            context = (
                self._ydl_factory(options) if self._ydl_factory
                else youtube_dl(options, self._cookie_file)
            )
            with context as provider:
                metadata = extract_with_metadata(
                    provider, source_url, download=False, cache=self._metadata_cache,
                )
        return parse_chapters(metadata)
