from app.models.transcriptions import JobStatus, Segment
from app.storage.jobs import SqliteJobStore
from app.workers.job_worker import JobWorker, TranscriptionResult


class SuccessfulProcessor:
    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        assert source_url == "https://www.youtube.com/watch?v=abc"
        assert requested_language == "es"
        return TranscriptionResult(
            language="es",
            duration_seconds=2.5,
            text="Receta de prueba",
            segments=[Segment(start=0, end=2.5, text="Receta de prueba")],
        )


class FailingProcessor:
    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        raise RuntimeError("detalle interno que no debe exponerse")


def test_worker_completes_a_queued_job(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    job = store.create("https://www.youtube.com/watch?v=abc", "es")
    worker = JobWorker(store, SuccessfulProcessor(), result_ttl_seconds=3600)

    completed = worker.process_next()

    assert completed is not None
    assert completed.id == job.id
    assert completed.status is JobStatus.COMPLETED
    assert completed.text == "Receta de prueba"
    assert completed.expires_at is not None
    store.close()


def test_worker_marks_failures_without_internal_error_details(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    job = store.create("https://www.youtube.com/watch?v=abc", None)
    worker = JobWorker(store, FailingProcessor(), result_ttl_seconds=3600)

    failed = worker.process_next()

    assert failed is not None
    assert failed.id == job.id
    assert failed.status is JobStatus.FAILED
    assert failed.error_message == "No se ha podido transcribir el vídeo."
    store.close()


def test_worker_returns_none_when_no_job_is_queued(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    worker = JobWorker(store, SuccessfulProcessor(), result_ttl_seconds=3600)

    assert worker.process_next() is None
    store.close()
