"""Adaptador de faster-whisper que usa exclusivamente un modelo local."""

from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.models.transcriptions import Segment
from app.workers.job_worker import TranscriptionResult


class WhisperSegment(Protocol):
    start: float
    end: float
    text: str


class WhisperInfo(Protocol):
    language: str


class WhisperModel(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str | None,
        vad_filter: bool,
        beam_size: int,
    ) -> tuple[Iterable[WhisperSegment], WhisperInfo]: ...


class LocalModelNotFoundError(FileNotFoundError):
    """El modelo requerido no existe en la ruta local configurada."""


class FasterWhisperTranscriber:
    """Transcribe audio con un modelo local, cargado una sola vez por proceso."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 2,
        beam_size: int = 5,
        model_factory: Callable[[str, str, str], WhisperModel] | None = None,
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._compute_type = compute_type
        self._cpu_threads = cpu_threads
        self._beam_size = beam_size
        self._model_factory = model_factory or self._default_model_factory
        self._model: WhisperModel | None = None
        self._model_lock = Lock()

    def transcribe(
        self,
        audio_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        """Convierte un audio local a texto y segmentos temporizados."""
        model = self._get_model()
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=requested_language,
            vad_filter=True,
            beam_size=self._beam_size,
        )
        segments = [
            Segment(start=segment.start, end=segment.end, text=segment.text.strip())
            for segment in raw_segments
            if segment.text.strip()
        ]
        return TranscriptionResult(
            language=info.language or requested_language,
            duration_seconds=max((segment.end for segment in segments), default=0),
            text=" ".join(segment.text for segment in segments),
            segments=segments,
        )

    def _get_model(self) -> WhisperModel:
        with self._model_lock:
            return self._load_model()

    def _load_model(self) -> WhisperModel:
        if self._model is None:
            if not self._model_path.is_dir():
                raise LocalModelNotFoundError(
                    f"No existe un modelo local en {self._model_path}."
                )
            self._model = self._model_factory(
                str(self._model_path),
                self._device,
                self._compute_type,
            )
        return self._model

    def _default_model_factory(
        self,
        model_path: str,
        device: str,
        compute_type: str,
    ) -> WhisperModel:
        from faster_whisper import WhisperModel as FasterWhisperModel

        return FasterWhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            cpu_threads=self._cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
