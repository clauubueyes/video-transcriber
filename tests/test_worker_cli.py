from app.core.config import Settings
from app.models.transcriptions import Segment
from app.storage.jobs import SqliteJobStore
from app.workers.cli import run_once
from app.workers.job_worker import TranscriptionResult


class SuccessfulProcessor:
    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        return TranscriptionResult(
            language="es",
            duration_seconds=1,
            text="Texto local",
            segments=[Segment(start=0, end=1, text="Texto local")],
        )


def test_standalone_worker_processes_pending_jobs_once(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    job = store.create("https://www.youtube.com/watch?v=abc", "es")
    settings = Settings(token="test-token", result_ttl_seconds=60)

    processed = run_once(settings, store, SuccessfulProcessor())
    completed = store.get(job.id)

    assert processed == 1
    assert completed is not None
    assert completed.text == "Texto local"
    store.close()
