"""Control de concurrencia para workers locales de transcripción."""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Protocol

from app.storage.jobs import StoredJob


class QueueWorker(Protocol):
    def process_next(self) -> StoredJob | None: ...


class BoundedJobRunner:
    """Ejecuta trabajos pendientes sin superar la concurrencia configurada."""

    def __init__(self, worker: QueueWorker, max_concurrent_jobs: int) -> None:
        self._worker = worker
        self._max_concurrent_jobs = max_concurrent_jobs
        self._semaphore = BoundedSemaphore(value=max_concurrent_jobs)

    def run_pending(self) -> int | None:
        """Vacía la cola usando hasta el máximo de procesamientos configurado.

        Cada hueco del semáforo representa un trabajo en curso, no una
        invocación completa del runner. De este modo una cola ya existente no
        queda serializada en una sola tarea de fondo.
        """
        acquired_slots = 0
        while acquired_slots < self._max_concurrent_jobs:
            if not self._semaphore.acquire(blocking=False):
                break
            acquired_slots += 1

        if not acquired_slots:
            return None

        try:
            with ThreadPoolExecutor(max_workers=acquired_slots) as executor:
                processed_counts = executor.map(
                    lambda _: self._process_available_jobs(), range(acquired_slots)
                )
                return sum(processed_counts)
        finally:
            for _ in range(acquired_slots):
                self._semaphore.release()

    def _process_available_jobs(self) -> int:
        """Procesa trabajos hasta que no quede ninguno que reclamar."""
        processed_jobs = 0
        while self._worker.process_next() is not None:
            processed_jobs += 1
        return processed_jobs
