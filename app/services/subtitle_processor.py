"""Procesador que aprovecha subtítulos antes de usar una transcripción de audio."""

import logging
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from yt_dlp.utils import DownloadError

from app.services.chapters import ChapterFetcher
from app.services.subtitles import SubtitleFetcher
from app.services.vtt import parse_vtt_file
from app.workers.job_worker import TranscriptionProcessor, TranscriptionResult

logger = logging.getLogger("video_transcriber.subtitles")


class SubtitleFirstProcessor:
    """Devuelve subtítulos disponibles o delega en un procesador de respaldo."""

    def __init__(
        self,
        subtitle_fetcher: SubtitleFetcher,
        audio_fallback: TranscriptionProcessor,
        *,
        chapter_fetcher: ChapterFetcher | None = None,
    ) -> None:
        self._subtitle_fetcher = subtitle_fetcher
        self._audio_fallback = audio_fallback
        self._chapter_fetcher = chapter_fetcher

    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        chapters = []
        if self._chapter_fetcher is not None:
            try:
                chapters = self._chapter_fetcher.fetch(source_url)
            except DownloadError:
                logger.warning("youtube_chapters_failed")
        with TemporaryDirectory(prefix="video-transcriber-") as temporary_directory:
            try:
                subtitle_path = self._subtitle_fetcher.fetch(
                    source_url,
                    requested_language,
                    Path(temporary_directory),
                )
            except DownloadError:
                logger.warning("youtube_subtitles_failed: se intenta descargar audio.")
                subtitle_path = None
            if subtitle_path is not None:
                subtitles = parse_vtt_file(subtitle_path)
                if subtitles.segments:
                    return TranscriptionResult(
                        language=requested_language,
                        duration_seconds=subtitles.duration_seconds,
                        text=subtitles.text,
                        segments=subtitles.segments,
                        chapters=chapters,
                    )

        result = self._audio_fallback.process(source_url, requested_language)
        return replace(result, chapters=chapters or result.chapters)
