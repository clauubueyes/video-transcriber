"""Procesador que aprovecha subtítulos antes de usar una transcripción de audio."""

from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.subtitles import SubtitleFetcher
from app.services.vtt import parse_vtt_file
from app.workers.job_worker import TranscriptionProcessor, TranscriptionResult


class SubtitleFirstProcessor:
    """Devuelve subtítulos disponibles o delega en un procesador de respaldo."""

    def __init__(
        self,
        subtitle_fetcher: SubtitleFetcher,
        audio_fallback: TranscriptionProcessor,
    ) -> None:
        self._subtitle_fetcher = subtitle_fetcher
        self._audio_fallback = audio_fallback

    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        with TemporaryDirectory(prefix="video-transcriber-") as temporary_directory:
            subtitle_path = self._subtitle_fetcher.fetch(
                source_url,
                requested_language,
                Path(temporary_directory),
            )
            if subtitle_path is not None:
                subtitles = parse_vtt_file(subtitle_path)
                if subtitles.segments:
                    return TranscriptionResult(
                        language=requested_language,
                        duration_seconds=subtitles.duration_seconds,
                        text=subtitles.text,
                        segments=subtitles.segments,
                    )

        return self._audio_fallback.process(source_url, requested_language)
