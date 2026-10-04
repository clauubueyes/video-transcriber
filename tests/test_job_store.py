from datetime import UTC, datetime, timedelta

import pytest

from app.models.transcriptions import Chapter, JobStatus, Segment, SourceType
from app.storage.jobs import (
    InvalidJobTransitionError,
    JobQueueFullError,
    SqliteJobStore,
)


@pytest.fixture
def store(tmp_path):
    job_store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    yield job_store
    job_store.close()


def test_store_creates_and_reads_a_queued_job(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", "es")

    restored = store.get(job.id)

    assert job.id.startswith("trn_")
    assert restored == job


def test_queue_capacity_counts_active_jobs_and_releases_failed_jobs(store):
    job = store.create("https://youtu.be/first", None, max_pending_jobs=1)
    store.claim_next_queued()
    assert store.has_capacity(1) is False
    with pytest.raises(JobQueueFullError):
        store.create("https://youtu.be/second", None, max_pending_jobs=1)
    store.update_status(job.id, JobStatus.FAILED)
    assert store.has_capacity(1) is True
    store.create("https://youtu.be/second", None, max_pending_jobs=1)


def test_queue_admission_is_atomic_across_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database = tmp_path / "shared.sqlite3"
    stores = [SqliteJobStore(database) for _ in range(4)]
    barrier = Barrier(4)

    def submit(store):
        barrier.wait(timeout=2)
        try:
            store.create("https://youtu.be/test", None, max_pending_jobs=1)
            return True
        except JobQueueFullError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(submit, stores)) == 1
        assert stores[0].metrics().queued_jobs == 1
    finally:
        for store in stores:
            store.close()


def test_store_persists_file_source_type(store: SqliteJobStore) -> None:
    job = store.create("tmp/upload.mp3", "es", source_type=SourceType.FILE)

    restored = store.get(job.id)

    assert restored is not None
    assert restored.source_type is SourceType.FILE


def test_store_lists_file_source_paths(store: SqliteJobStore) -> None:
    store.create("tmp/upload-a.webm", "es", source_type=SourceType.FILE)
    store.create("https://www.youtube.com/watch?v=abc", "es")

    paths = store.file_source_paths()

    assert paths == {"tmp/upload-a.webm"}


def test_store_reports_operational_metrics(store: SqliteJobStore) -> None:
    store.create("https://www.youtube.com/watch?v=queued", "es")
    active = store.create("https://www.youtube.com/watch?v=active", "es")
    failed = store.create("https://www.youtube.com/watch?v=failed", "es")
    completed = store.create("https://www.youtube.com/watch?v=completed", "es")
    store.update_status(active.id, JobStatus.DOWNLOADING)
    store.update_status(failed.id, JobStatus.FAILED)
    store.update_status(completed.id, JobStatus.DOWNLOADING)
    store.update_status(completed.id, JobStatus.TRANSCRIBING)
    store.complete(
        completed.id,
        language="es",
        duration_seconds=12.5,
        text="Completada",
        segments=[Segment(start=0, end=12.5, text="Completada")],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    metrics = store.metrics()

    assert metrics.queued_jobs == 1
    assert metrics.active_jobs == 1
    assert metrics.completed_jobs == 1
    assert metrics.failed_jobs == 1
    assert metrics.average_completed_duration_seconds == 12.5


def test_store_persists_valid_status_transition(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    updated = store.update_status(job.id, JobStatus.DOWNLOADING)

    assert updated is not None
    assert updated.status is JobStatus.DOWNLOADING


def test_store_claims_each_queued_job_once(store: SqliteJobStore) -> None:
    first = store.create("https://www.youtube.com/watch?v=first", None)
    second = store.create("https://www.youtube.com/watch?v=second", None)

    first_claim = store.claim_next_queued()
    second_claim = store.claim_next_queued()

    assert first_claim is not None
    assert first_claim.id == first.id
    assert first_claim.status is JobStatus.DOWNLOADING
    assert second_claim is not None
    assert second_claim.id == second.id
    assert store.claim_next_queued() is None


def test_store_rejects_invalid_status_transition(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    with pytest.raises(InvalidJobTransitionError, match="queued"):
        store.update_status(job.id, JobStatus.COMPLETED)


def test_store_persists_completed_transcription_result(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)
    store.update_status(job.id, JobStatus.DOWNLOADING)
    store.update_status(job.id, JobStatus.TRANSCRIBING)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    completed = store.complete(
        job.id,
        language="es",
        duration_seconds=4.2,
        text="Hola mundo",
        segments=[Segment(start=0, end=4.2, text="Hola mundo")],
        expires_at=expires_at,
        chapters=[Chapter(start=0, end=4.2, title="Introducción")],
    )

    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.text == "Hola mundo"
    assert completed.segments == [Segment(start=0, end=4.2, text="Hola mundo")]
    assert completed.expires_at == expires_at
    assert completed.chapters == [Chapter(start=0, end=4.2, title="Introducción")]
    assert store.get(job.id).chapters == completed.chapters


def test_store_expires_and_clears_due_transcription_results(
    store: SqliteJobStore,
) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)
    store.update_status(job.id, JobStatus.DOWNLOADING)
    store.update_status(job.id, JobStatus.TRANSCRIBING)
    store.complete(
        job.id,
        language="es",
        duration_seconds=4.2,
        text="Hola mundo",
        segments=[Segment(start=0, end=4.2, text="Hola mundo")],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        chapters=[Chapter(start=0, end=4.2, title="Introducción")],
    )

    expired_count = store.expire_due_results(datetime.now(UTC))
    expired = store.get(job.id)

    assert expired_count == 1
    assert expired is not None
    assert expired.status is JobStatus.EXPIRED
    assert expired.text is None
    assert expired.segments is None
    assert expired.chapters is None
    assert expired.duration_seconds is None
    assert expired.expires_at is None


def test_store_requeues_stale_active_jobs(store: SqliteJobStore) -> None:
    downloading = store.create("https://www.youtube.com/watch?v=downloading", None)
    transcribing = store.create("https://www.youtube.com/watch?v=transcribing", None)
    recent = store.create("https://www.youtube.com/watch?v=recent", None)
    store.update_status(downloading.id, JobStatus.DOWNLOADING)
    store.update_status(transcribing.id, JobStatus.DOWNLOADING)
    store.update_status(transcribing.id, JobStatus.TRANSCRIBING)
    store.update_status(recent.id, JobStatus.DOWNLOADING)

    requeued = store.requeue_stale_active_jobs(datetime.now(UTC) + timedelta(seconds=1))

    assert requeued == 3
    assert store.get(downloading.id).status is JobStatus.QUEUED  # type: ignore[union-attr]
    assert store.get(transcribing.id).status is JobStatus.QUEUED  # type: ignore[union-attr]
    assert store.get(recent.id).status is JobStatus.QUEUED  # type: ignore[union-attr]


def test_store_deletes_job(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    assert store.delete(job.id) is True
    assert store.get(job.id) is None
    assert store.delete(job.id) is False


def test_existing_database_migrates_without_losing_results(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE transcription_jobs (
                id TEXT PRIMARY KEY, source_url TEXT NOT NULL, language TEXT,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, error_message TEXT,
                duration_seconds REAL, transcript_text TEXT,
                segments_json TEXT, expires_at TEXT
            )
        """)
        connection.execute("""
            INSERT INTO transcription_jobs
            VALUES ('trn_legacy', 'https://youtu.be/abc', 'es', 'completed',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                    NULL, 1, 'Hola', '[{"start":0,"end":1,"text":"Hola"}]', NULL)
        """)
    store = SqliteJobStore(path)
    try:
        restored = store.get("trn_legacy")
        assert restored.text == "Hola"
        assert restored.chapters is None
        assert restored.segments == [Segment(start=0, end=1, text="Hola")]
        assert store.create("https://youtu.be/new", None).chapters is None
    finally:
        store.close()
