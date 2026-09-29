"""Orquestación local del ciclo de vida de un trabajo."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.models.transcriptions import JobStatus, Segment
from app.storage.jobs import SqliteJobStore, StoredJob


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado normalizado devuelto por un adaptador de transcripción local."""

    language: str | None
    duration_seconds: float
    text: str
    segments: list[Segment]


class TranscriptionProcessor(Protocol):
    """Adaptador que obtiene y transcribe una fuente sin depender de la API."""

    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult: ...


class JobWorker:
    """Procesa un trabajo pendiente por invocación, con resultados temporales."""

    def __init__(
        self,
        store: SqliteJobStore,
        processor: TranscriptionProcessor,
        result_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._processor = processor
        self._result_ttl_seconds = result_ttl_seconds

    def process_next(self) -> StoredJob | None:
        """Reclama y procesa un trabajo o devuelve ``None`` si la cola está vacía."""
        job = self._store.claim_next_queued()
        if job is None:
            return None

        try:
            active_job = self._store.update_status(job.id, JobStatus.TRANSCRIBING)
            if active_job is None:
                return None

            result = self._processor.process(
                active_job.source_url,
                active_job.language,
            )
            return self._store.complete(
                active_job.id,
                language=result.language,
                duration_seconds=result.duration_seconds,
                text=result.text,
                segments=result.segments,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self._result_ttl_seconds),
            )
        except Exception:
            return self._store.update_status(
                job.id,
                JobStatus.FAILED,
                error_message="No se ha podido transcribir el vídeo.",
            )
