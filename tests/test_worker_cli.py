from pathlib import Path

from app.core.config import Settings
from app.models.transcriptions import Segment, SourceType
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


class SuccessfulFileProcessor:
    def process(
        self,
        source_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        assert source_path.read_bytes() == b"audio local"
        assert requested_language == "es"
        return TranscriptionResult(
            language="es",
            duration_seconds=1,
            text="Archivo local",
            segments=[Segment(start=0, end=1, text="Archivo local")],
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


def test_standalone_worker_processes_pending_local_upload(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    upload = tmp_path / "upload.webm"
    upload.write_bytes(b"audio local")
    job = store.create(str(upload), "es", source_type=SourceType.FILE)
    settings = Settings(token="test-token", result_ttl_seconds=60)

    processed = run_once(
        settings,
        store,
        SuccessfulProcessor(),
        SuccessfulFileProcessor(),
    )
    completed = store.get(job.id)

    assert processed == 1
    assert completed is not None
    assert completed.text == "Archivo local"
    assert not upload.exists()
    store.close()
