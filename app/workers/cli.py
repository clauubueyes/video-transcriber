"""Punto de entrada para ejecutar el worker como proceso separado."""

import argparse
import logging
from datetime import UTC, datetime, timedelta
from time import sleep

from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.processor_factory import (
    create_groq_file_processor,
    create_groq_processor,
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

logger = logging.getLogger("video_transcriber.worker")


def run_once(
    settings: Settings,
    store: SqliteJobStore,
    processor: TranscriptionProcessor,
    file_processor: FileTranscriptionProcessor | None = None,
) -> int | None:
    """Procesa los trabajos pendientes una vez respetando la concurrencia."""
    expired_results = store.expire_due_results(datetime.now(UTC))
    if expired_results:
        logger.info(
            "expired_results_removed", extra={"expired_results": expired_results}
        )
    requeued_jobs = store.requeue_stale_active_jobs(
        datetime.now(UTC) - timedelta(seconds=settings.stale_job_timeout_seconds)
    )
    if requeued_jobs:
        logger.warning("stale_jobs_requeued", extra={"requeued_jobs": requeued_jobs})
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
    configure_logging()
    settings = Settings()
    store = SqliteJobStore(settings.database_path)
    upload_store = TemporaryUploadStore(
        settings.temporary_directory,
        settings.max_upload_bytes,
    )
    removed_uploads = upload_store.remove_orphaned(
        store.file_source_paths(),
        settings.orphan_upload_age_seconds,
    )
    if removed_uploads:
        logger.info(
            "orphaned_uploads_removed",
            extra={"removed_uploads": removed_uploads},
        )
    if settings.groq_api_key and settings.groq_api_key.get_secret_value():
        api_key = settings.groq_api_key.get_secret_value()
        processor = create_groq_processor(
            api_key,
            settings.groq_model,
            cookie_file=settings.youtube_cookie_file,
        )
        file_processor = create_groq_file_processor(api_key, settings.groq_model)
    else:
        processor = create_local_processor(
            settings.model_path,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            cookie_file=settings.youtube_cookie_file,
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
