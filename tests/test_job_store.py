from datetime import UTC, datetime, timedelta

import pytest

from app.models.transcriptions import JobStatus, Segment, SourceType
from app.storage.jobs import InvalidJobTransitionError, SqliteJobStore


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
    )

    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.text == "Hola mundo"
    assert completed.segments == [Segment(start=0, end=4.2, text="Hola mundo")]
    assert completed.expires_at == expires_at


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
    )

    expired_count = store.expire_due_results(datetime.now(UTC))
    expired = store.get(job.id)

    assert expired_count == 1
    assert expired is not None
    assert expired.status is JobStatus.EXPIRED
    assert expired.text is None
    assert expired.segments is None
    assert expired.duration_seconds is None
    assert expired.expires_at is None


def test_store_deletes_job(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    assert store.delete(job.id) is True
    assert store.get(job.id) is None
    assert store.delete(job.id) is False
