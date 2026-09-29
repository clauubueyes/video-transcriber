"""Repositorio SQLite para el ciclo de vida de trabajos de transcripción."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.models.transcriptions import JobStatus


class InvalidJobTransitionError(ValueError):
    """El trabajo no puede cambiar al estado solicitado."""


@dataclass(frozen=True)
class StoredJob:
    id: str
    source_url: str
    language: str | None
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset(
        {JobStatus.DOWNLOADING, JobStatus.FAILED, JobStatus.EXPIRED}
    ),
    JobStatus.DOWNLOADING: frozenset(
        {JobStatus.TRANSCRIBING, JobStatus.FAILED, JobStatus.EXPIRED}
    ),
    JobStatus.TRANSCRIBING: frozenset(
        {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.EXPIRED}
    ),
    JobStatus.COMPLETED: frozenset({JobStatus.EXPIRED}),
    JobStatus.FAILED: frozenset({JobStatus.EXPIRED}),
    JobStatus.EXPIRED: frozenset(),
}


class SqliteJobStore:
    """Almacena metadatos de trabajos sin conservar su audio o resultados."""

    def __init__(self, database_path: str | Path) -> None:
        if str(database_path) != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def create(self, source_url: str, language: str | None) -> StoredJob:
        now = datetime.now(UTC)
        job = StoredJob(
            id=f"trn_{uuid4().hex}",
            source_url=source_url,
            language=language,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            error_message=None,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO transcription_jobs
                    (
                        id, source_url, language, status, created_at, updated_at,
                        error_message
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                self._as_row(job),
            )
        return job

    def get(self, job_id: str) -> StoredJob | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def claim_next_queued(self) -> StoredJob | None:
        """Reclama el trabajo más antiguo pendiente para un único worker."""
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT id FROM transcription_jobs
                WHERE status = ?
                ORDER BY created_at, id
                LIMIT 1
                """,
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None

            job_id = row["id"]
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.DOWNLOADING.value,
                    datetime.now(UTC).isoformat(),
                    job_id,
                    JobStatus.QUEUED.value,
                ),
            )
            claimed = self.get(job_id)
        return claimed

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error_message: str | None = None,
    ) -> StoredJob | None:
        with self._lock, self._connection:
            job = self.get(job_id)
            if job is None:
                return None
            if status not in _ALLOWED_TRANSITIONS[job.status]:
                raise InvalidJobTransitionError(
                    f"No se puede cambiar de {job.status} a {status}."
                )
            updated_at = datetime.now(UTC)
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET status = ?, updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status.value, updated_at.isoformat(), error_message, job_id),
            )
        return self.get(job_id)

    def delete(self, job_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM transcription_jobs WHERE id = ?", (job_id,)
            )
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transcription_jobs (
                    id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    language TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                )
                """
            )

    @staticmethod
    def _as_row(
        job: StoredJob,
    ) -> tuple[str, str, str | None, str, str, str, str | None]:
        return (
            job.id,
            job.source_url,
            job.language,
            job.status.value,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            None,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredJob:
        return StoredJob(
            id=row["id"],
            source_url=row["source_url"],
            language=row["language"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_message=row["error_message"],
        )
