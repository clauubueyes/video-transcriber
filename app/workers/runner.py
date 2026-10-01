"""Control de concurrencia para workers locales de transcripción."""

from threading import BoundedSemaphore
from typing import Protocol

from app.storage.jobs import StoredJob


class QueueWorker(Protocol):
    def process_next(self) -> StoredJob | None: ...


class BoundedJobRunner:
    """Ejecuta trabajos pendientes sin superar la concurrencia configurada."""

    def __init__(self, worker: QueueWorker, max_concurrent_jobs: int) -> None:
        self._worker = worker
        self._semaphore = BoundedSemaphore(value=max_concurrent_jobs)

    def run_pending(self) -> int | None:
        """Procesa la cola disponible o devuelve ``None`` si está ocupada."""
        if not self._semaphore.acquire(blocking=False):
            return None

        processed_jobs = 0
        try:
            while self._worker.process_next() is not None:
                processed_jobs += 1
        finally:
            self._semaphore.release()
        return processed_jobs
