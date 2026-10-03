"""Orquestación local del ciclo de vida de un trabajo."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.models.transcriptions import JobStatus, Segment, SourceType
from app.storage.jobs import SqliteJobStore, StoredJob

logger = logging.getLogger("video_transcriber.worker")


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


class FileTranscriptionProcessor(Protocol):
    """Adaptador que transcribe un fichero local ya recibido por la aplicación."""

    def process(
        self,
        source_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult: ...


class JobWorker:
    """Procesa un trabajo pendiente por invocación, con resultados temporales."""

    def __init__(
        self,
        store: SqliteJobStore,
        processor: TranscriptionProcessor,
        result_ttl_seconds: int,
        file_processor: FileTranscriptionProcessor | None = None,
    ) -> None:
        self._store = store
        self._processor = processor
        self._result_ttl_seconds = result_ttl_seconds
        self._file_processor = file_processor

    def process_next(self) -> StoredJob | None:
        """Reclama y procesa un trabajo o devuelve ``None`` si la cola está vacía."""
        job = self._store.claim_next_queued()
        if job is None:
            return None

        logger.info(
            "job_claimed",
            extra={"job_id": job.id, "status": job.status.value},
        )

        try:
            active_job = self._store.update_status(job.id, JobStatus.TRANSCRIBING)
            if active_job is None:
                return None
            logger.info(
                "job_transcribing",
                extra={"job_id": active_job.id, "status": active_job.status.value},
            )

            result = self._process_source(active_job)
            completed_job = self._store.complete(
                active_job.id,
                language=result.language,
                duration_seconds=result.duration_seconds,
                text=result.text,
                segments=result.segments,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self._result_ttl_seconds),
            )
            if completed_job is not None:
                logger.info(
                    "job_completed",
                    extra={
                        "job_id": completed_job.id,
                        "status": completed_job.status.value,
                        "duration_seconds": completed_job.duration_seconds,
                    },
                )
            return completed_job
        except Exception as err:
            msg = "No se ha podido transcribir el vídeo."
            if "No existe un modelo local" in str(err):
                msg = "No hay modelo local de Whisper. Configura VIDEO_TRANSCRIBER_GROQ_API_KEY en .env para transcripción gratuita en la nube."
            failed_job = self._store.update_status(
                job.id,
                JobStatus.FAILED,
                error_message=msg,
            )
            if failed_job is not None:
                logger.warning(
                    "job_failed",
                    extra={"job_id": failed_job.id, "status": failed_job.status.value},
                    exc_info=True,
                )
            return failed_job
        finally:
            self._remove_temporary_upload(job)

    def _process_source(self, job: StoredJob) -> TranscriptionResult:
        if job.source_type is SourceType.FILE:
            if self._file_processor is None:
                message = "No hay procesador configurado para ficheros locales."
                raise RuntimeError(message)
            return self._file_processor.process(Path(job.source_url), job.language)
        return self._processor.process(job.source_url, job.language)

    @staticmethod
    def _remove_temporary_upload(job: StoredJob) -> None:
        if job.source_type is not SourceType.FILE:
            return
        try:
            Path(job.source_url).unlink(missing_ok=True)
        except OSError:
            logger.warning("temporary_upload_cleanup_failed", extra={"job_id": job.id})
