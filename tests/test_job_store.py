import pytest

from app.models.transcriptions import JobStatus
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


def test_store_persists_valid_status_transition(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    updated = store.update_status(job.id, JobStatus.DOWNLOADING)

    assert updated is not None
    assert updated.status is JobStatus.DOWNLOADING


def test_store_rejects_invalid_status_transition(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    with pytest.raises(InvalidJobTransitionError, match="queued"):
        store.update_status(job.id, JobStatus.COMPLETED)


def test_store_deletes_job(store: SqliteJobStore) -> None:
    job = store.create("https://www.youtube.com/watch?v=abc", None)

    assert store.delete(job.id) is True
    assert store.get(job.id) is None
    assert store.delete(job.id) is False
