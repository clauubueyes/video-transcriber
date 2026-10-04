from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from app.models.transcriptions import JobStatus, ProcessingMethod, Segment


def client_with_settings(tmp_path) -> TestClient:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        allowed_domains="youtube.com,www.youtube.com,youtu.be",
        temporary_directory=tmp_path / "uploads",
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


def test_create_transcription_accepts_one_hour_and_rejects_longer_video(tmp_path):
    client = client_with_settings(tmp_path)
    probe = FixedDurationProbe(3600)
    client.app.dependency_overrides[get_video_duration_probe] = lambda: probe
    payload = {"source": {"type": "url", "url": "https://youtu.be/abc"}}
    headers = {"Authorization": "Bearer test-token"}
    assert client.post("/v1/transcriptions", json=payload,
                       headers=headers).status_code == 202
    probe.duration = 3601
    response = client.post("/v1/transcriptions", json=payload, headers=headers)
    assert response.status_code == 400
    assert "60 min." in response.json()["detail"]


def test_full_queue_rejects_urls_before_network_and_uploads_before_copy(tmp_path):
    from unittest.mock import Mock

    client = client_with_settings(tmp_path)
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token", max_pending_jobs=1,
        temporary_directory=tmp_path / "uploads", _env_file=None,
    )
    client.app.state.job_store.create("https://youtu.be/pending", None)
    probe = Mock()
    client.app.dependency_overrides[get_video_duration_probe] = lambda: probe
    headers = {"Authorization": "Bearer test-token"}
    response = client.post("/v1/transcriptions", headers=headers, json={
        "source": {"type": "url", "url": "https://youtu.be/abc"},
    })
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    probe.get_duration_seconds.assert_not_called()
    response = client.post("/v1/transcriptions/upload", headers=headers,
                           files={"file": ("audio.mp3", b"audio", "audio/mpeg")})
    assert response.status_code == 503
    assert not (tmp_path / "uploads").exists()


def test_upload_is_removed_when_another_request_fills_the_queue(tmp_path):
    from unittest.mock import patch

    from app.storage.jobs import JobQueueFullError

    client = client_with_settings(tmp_path)
    with patch.object(client.app.state.job_store, "create",
                      side_effect=JobQueueFullError()):
        response = client.post(
            "/v1/transcriptions/upload",
            headers={"Authorization": "Bearer test-token"},
            files={"file": ("audio.mp3", b"audio", "audio/mpeg")},
        )
    assert response.status_code == 503
    assert not list((tmp_path / "uploads").iterdir())


def test_concurrent_requests_share_one_worker_and_one_runner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from time import sleep
    from unittest.mock import patch

    from fastapi import Request

    from app.api.routes.transcriptions import get_job_runner

    app = create_app(tmp_path / "jobs.sqlite3")
    request = Request({"type": "http", "app": app})
    settings = Settings(token="test-token", _env_file=None)
    barrier = Barrier(4)

    def processors(_, **kwargs):
        sleep(0.02)
        return object(), object()

    def initialize(_):
        barrier.wait(timeout=2)
        worker = get_job_worker(request, settings, app.state.job_store)
        runner = get_job_runner(request, settings, worker, app.state.job_store)
        return worker, runner

    with patch("app.api.routes.transcriptions.create_processors",
               side_effect=processors) as factory:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(initialize, range(4)))
    assert len({id(worker) for worker, _ in results}) == 1
    assert len({id(runner) for _, runner in results}) == 1
    assert factory.call_count == 1


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


def test_create_uploaded_transcription_queues_a_local_file(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.post(
        "/v1/transcriptions/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("receta.webm", b"audio local", "audio/webm")},
        data={"language": "es"},
    )

    assert response.status_code == 202
    job = client.app.state.job_store.get(response.json()["id"])
    assert job is not None
    assert job.source_type.value == "file"
    assert job.language == "es"
    assert job.source_url.endswith(".webm")
    assert (tmp_path / "uploads").exists()


def test_create_uploaded_transcription_rejects_unsupported_files(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    response = client.post(
        "/v1/transcriptions/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("receta.txt", b"no es audio", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "El formato de archivo no es compatible."}


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
        "detail": "El vídeo supera el límite de duración para importar: 1 min."
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


def test_get_transcription_metrics_returns_only_aggregates(tmp_path) -> None:
    client = client_with_settings(tmp_path)
    headers = {"Authorization": "Bearer test-token"}
    client.app.state.job_store.create("https://www.youtube.com/watch?v=queued", "es")

    response = client.get("/v1/transcriptions/metrics", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "queuedJobs": 1,
        "activeJobs": 0,
        "completedJobs": 0,
        "failedJobs": 0,
        "averageCompletedDurationSeconds": None,
        "performanceByMethod": [],
    }


def test_get_transcription_metrics_requires_authentication(tmp_path) -> None:
    client = client_with_settings(tmp_path)

    assert client.get("/v1/transcriptions/metrics").status_code == 401


def test_api_exposes_persisted_performance_and_keeps_aggregates_private(tmp_path):
    client = client_with_settings(tmp_path)
    headers = {"Authorization": "Bearer test-token"}
    store = client.app.state.job_store
    job = store.create("https://youtu.be/private-source", "es")
    store.update_status(job.id, JobStatus.DOWNLOADING)
    store.update_status(job.id, JobStatus.TRANSCRIBING)
    store.complete(
        job.id, language="es", duration_seconds=120,
        text="Private transcription", segments=[],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        processing_seconds=2, processing_method=ProcessingMethod.GROQ,
    )

    response = client.get(f"/v1/transcriptions/{job.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["processingSeconds"] == 2
    assert response.json()["processingMethod"] == "groq"
    assert response.json()["processingSpeed"] == 60

    metrics = client.get("/v1/transcriptions/metrics", headers=headers)
    assert metrics.status_code == 200
    assert metrics.json()["performanceByMethod"] == [{
        "method": "groq", "completedJobs": 1, "measuredJobs": 1,
        "averageProcessingSeconds": 2, "processingSpeed": 60,
    }]
    assert "Private" not in metrics.text
    assert "private-source" not in metrics.text
    assert job.id not in metrics.text


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


def test_delete_transcription_removes_a_queued_upload(tmp_path) -> None:
    client = client_with_settings(tmp_path)
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/v1/transcriptions/upload",
        headers=headers,
        files={"file": ("receta.webm", b"audio local", "audio/webm")},
    )
    job = client.app.state.job_store.get(created.json()["id"])
    assert job is not None
    source_path = job.source_url

    deleted = client.delete(f"/v1/transcriptions/{job.id}", headers=headers)

    assert deleted.status_code == 204
    assert not Path(source_path).exists()
