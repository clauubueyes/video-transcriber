from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.api.routes.transcriptions import (
    get_job_worker,
    get_public_host_validator,
    get_redirect_validator,
    get_video_duration_probe,
)
from app.core.config import Settings
from app.main import create_app
from app.models.transcriptions import JobStatus, Segment


def client_with_settings(tmp_path) -> TestClient:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        allowed_domains="youtube.com,www.youtube.com,youtu.be",
    )
    app.dependency_overrides[get_job_worker] = lambda: RecordingWorker()
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(60)
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    return TestClient(app)


class RecordingWorker:
    def __init__(self) -> None:
        self.calls = 0

    def process_next(self) -> None:
        self.calls += 1


class FixedDurationProbe:
    def __init__(self, duration: float | None) -> None:
        self.duration = duration

    def get_duration_seconds(self, source_url: str) -> float | None:
        return self.duration


def allow_public_host(host: str) -> object:
    return object()


def identity_redirect(source_url: str) -> str:
    return source_url


def test_create_transcription_queues_a_valid_youtube_job(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
            "language": "es",
        },
    )

    assert response.status_code == 202
    assert response.json()["id"].startswith("trn_")
    assert response.json()["status"] == "queued"
    assert response.json()["language"] == "es"


def test_create_transcription_schedules_the_local_worker(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    worker = RecordingWorker()
    app.dependency_overrides[get_settings] = lambda: Settings(token="test-token")
    app.dependency_overrides[get_job_worker] = lambda: worker
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(60)
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    client = TestClient(app)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    assert response.status_code == 202
    assert worker.calls == 1


def test_create_transcription_can_leave_job_for_standalone_worker(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    worker = RecordingWorker()
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        process_jobs_in_api=False,
    )
    app.dependency_overrides[get_job_worker] = lambda: worker
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(60)
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    client = TestClient(app)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert worker.calls == 0


def test_create_transcription_rejects_unconfigured_providers(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://example.com/video"},
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Este proveedor de vídeo no es compatible."}


def test_create_transcription_requires_bearer_token(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.post(
        "/v1/transcriptions",
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    assert response.status_code == 401


def test_create_transcription_rejects_videos_over_duration_limit(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        max_duration_seconds=60,
    )
    app.dependency_overrides[get_job_worker] = lambda: RecordingWorker()
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(61)
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    client = TestClient(app)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "El vídeo supera el límite de duración para importar."
    }


def test_create_transcription_rejects_videos_without_duration(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(token="test-token")
    app.dependency_overrides[get_job_worker] = lambda: RecordingWorker()
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(
        None
    )
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    client = TestClient(app)

    response = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "No hemos podido determinar la duración del vídeo."
    }


def test_create_transcription_limits_jobs_per_token(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        max_jobs_per_token=1,
    )
    app.dependency_overrides[get_job_worker] = lambda: RecordingWorker()
    app.dependency_overrides[get_video_duration_probe] = lambda: FixedDurationProbe(60)
    app.dependency_overrides[get_public_host_validator] = lambda: allow_public_host
    app.dependency_overrides[get_redirect_validator] = lambda: identity_redirect
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
    }

    first = client.post("/v1/transcriptions", headers=headers, json=payload)
    second = client.post("/v1/transcriptions", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "3600"


def test_get_transcription_returns_the_queued_job(tmp_path) -> None:
    client = client_with_settings(tmp_path)
    created = client.post(
        "/v1/transcriptions",
        headers={"Authorization": "Bearer test-token"},
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )

    response = client.get(
        f"/v1/transcriptions/{created.json()['id']}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert response.json()["status"] == "queued"


def test_get_transcription_returns_not_found_for_unknown_job(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.get(
        "/v1/transcriptions/trn_missing",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404


def test_get_transcription_expires_due_result_before_responding(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(token="test-token")
    app.dependency_overrides[get_job_worker] = lambda: RecordingWorker()
    job = app.state.job_store.create("https://www.youtube.com/watch?v=abc", "es")
    app.state.job_store.update_status(job.id, JobStatus.DOWNLOADING)
    app.state.job_store.update_status(job.id, JobStatus.TRANSCRIBING)
    app.state.job_store.complete(
        job.id,
        language="es",
        duration_seconds=1,
        text="Caducada",
        segments=[Segment(start=0, end=1, text="Caducada")],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    client = TestClient(app)

    response = client.get(
        f"/v1/transcriptions/{job.id}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "expired"
    assert response.json()["text"] is None


def test_delete_transcription_removes_a_job_idempotently(tmp_path) -> None:
    client = client_with_settings(tmp_path)
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/v1/transcriptions",
        headers=headers,
        json={
            "source": {"type": "url", "url": "https://www.youtube.com/watch?v=abc"},
        },
    )
    job_id = created.json()["id"]

    deleted = client.delete(f"/v1/transcriptions/{job_id}", headers=headers)
    repeated = client.delete(f"/v1/transcriptions/{job_id}", headers=headers)
    retrieved = client.get(f"/v1/transcriptions/{job_id}", headers=headers)

    assert deleted.status_code == 204
    assert repeated.status_code == 204
    assert retrieved.status_code == 404
