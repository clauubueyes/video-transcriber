"""Punto de entrada para ejecutar el worker como proceso separado."""

import argparse
from time import sleep

from app.core.config import Settings
from app.services.processor_factory import (
    create_local_file_processor,
    create_local_processor,
)
from app.services.uploads import TemporaryUploadStore
from app.storage.jobs import SqliteJobStore
from app.workers.job_worker import (
    FileTranscriptionProcessor,
    JobWorker,
    TranscriptionProcessor,
)
from app.workers.runner import BoundedJobRunner


def run_once(
    settings: Settings,
    store: SqliteJobStore,
    processor: TranscriptionProcessor,
    file_processor: FileTranscriptionProcessor | None = None,
) -> int | None:
    """Procesa los trabajos pendientes una vez respetando la concurrencia."""
    worker = JobWorker(
        store,
        processor,
        settings.result_ttl_seconds,
        file_processor=file_processor,
    )
    runner = BoundedJobRunner(worker, settings.max_concurrent_jobs)
    return runner.run_pending()


def run_forever(
    settings: Settings,
    store: SqliteJobStore,
    processor: TranscriptionProcessor,
    file_processor: FileTranscriptionProcessor | None = None,
) -> None:
    """Procesa cola continuamente; un supervisor externo gestiona el proceso."""
    while True:
        processed = run_once(settings, store, processor, file_processor)
        if not processed:
            sleep(settings.worker_poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker local de Video Transcriber")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Procesa los trabajos disponibles una vez y termina.",
    )
    arguments = parser.parse_args()
    settings = Settings()
    store = SqliteJobStore(settings.database_path)
    upload_store = TemporaryUploadStore(
        settings.temporary_directory,
        settings.max_upload_bytes,
    )
    upload_store.remove_orphaned(
        store.file_source_paths(),
        settings.orphan_upload_age_seconds,
    )
    processor = create_local_processor(
        settings.model_path,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    file_processor = create_local_file_processor(
        settings.model_path,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    try:
        if arguments.once:
            run_once(settings, store, processor, file_processor)
        else:
            run_forever(settings, store, processor, file_processor)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
