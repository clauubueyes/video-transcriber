"""Procesamiento de vídeos o audios almacenados temporalmente en disco."""

from pathlib import Path

from app.services.audio_processor import AudioTranscriber
from app.workers.job_worker import TranscriptionResult


class LocalFileProcessor:
    """Transcribe directamente un fichero sin descargar ni usar servicios externos."""

    def __init__(self, transcriber: AudioTranscriber) -> None:
        self._transcriber = transcriber

    def process(
        self,
        source_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        return self._transcriber.transcribe(source_path, requested_language)
