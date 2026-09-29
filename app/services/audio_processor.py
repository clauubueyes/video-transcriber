"""Procesador que obtiene audio temporal y lo transcribe localmente."""

from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.audio import AudioFetcher
from app.services.whisper import FasterWhisperTranscriber
from app.workers.job_worker import TranscriptionResult


class AudioWhisperProcessor:
    """Implementa el respaldo de audio usado cuando no existen subtítulos."""

    def __init__(
        self,
        audio_fetcher: AudioFetcher,
        transcriber: FasterWhisperTranscriber,
    ) -> None:
        self._audio_fetcher = audio_fetcher
        self._transcriber = transcriber

    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        with TemporaryDirectory(prefix="video-transcriber-") as temporary_directory:
            audio_path = self._audio_fetcher.fetch(
                source_url,
                Path(temporary_directory),
            )
            return self._transcriber.transcribe(audio_path, requested_language)
