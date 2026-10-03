from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.api.routes.transcriptions import (
    get_public_host_validator,
    get_redirect_validator,
    get_upload_store,
    get_video_duration_probe,
)
from app.core.config import Settings
from app.main import create_app
from app.services.uploads import TemporaryUploadStore


class DurationProbe:
    def get_duration_seconds(self, source_url: str) -> float:
        return 60


def web_client(tmp_path, **options) -> TestClient:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="private-service-secret", process_jobs_in_api=False, **options
    )
    app.dependency_overrides[get_public_host_validator] = lambda: lambda host: None
    app.dependency_overrides[get_redirect_validator] = lambda: lambda url: url
    app.dependency_overrides[get_video_duration_probe] = DurationProbe
    app.dependency_overrides[get_upload_store] = lambda: TemporaryUploadStore(
        tmp_path / "uploads", max_upload_bytes=100
    )
    return TestClient(app)


def create_job(client):
    return client.post("/web/jobs", json={
        "source": {"type": "url", "url": "https://youtu.be/Y8KsRjl3RiY"}
    })


def test_public_web_creates_job_without_service_token(tmp_path):
    client = web_client(tmp_path)
    response = create_job(client)
    assert response.status_code == 202
    data = response.json()
    assert "private-service-secret" not in response.text
    path = f"/web/jobs/{data['job']['id']}"
    assert client.get(path).status_code == 404
    assert client.get(path, headers={"X-Job-Key": "wrong"}).status_code == 404
    result = client.get(path, headers={"X-Job-Key": data["accessKey"]})
    assert result.status_code == 200
    assert result.json()["status"] == "queued"
    assert result.headers["cache-control"] == "no-store"


def test_public_web_returns_actionable_error_when_youtube_is_blocked(tmp_path):
    from yt_dlp.utils import DownloadError

    from app.services.duration import YtDlpVideoDurationProbe

    def blocked_factory(options):
        raise DownloadError("Sign in to confirm you're not a bot")

    client = web_client(tmp_path)
    client.app.dependency_overrides[get_video_duration_probe] = (
        lambda: YtDlpVideoDurationProbe(blocked_factory)
    )
    response = create_job(client)
    assert response.status_code == 502
    assert "Subir Archivo" in response.json()["detail"]
    assert client.app.state.job_store.claim_next_queued() is None


def test_access_key_cannot_read_another_job(tmp_path):
    client = web_client(tmp_path)
    first = create_job(client).json()
    second = create_job(client).json()
    assert client.get(
        f"/web/jobs/{second['job']['id']}",
        headers={"X-Job-Key": first["accessKey"]},
    ).status_code == 404


def test_public_web_can_be_disabled(tmp_path):
    client = web_client(tmp_path, public_web_enabled=False)
    assert create_job(client).status_code == 404


def test_public_web_limits_global_submissions(tmp_path):
    client = web_client(tmp_path, public_jobs_per_hour=1)
    assert create_job(client).status_code == 202
    assert create_job(client).status_code == 429


def test_public_upload_is_queued_and_requires_its_access_key(tmp_path):
    client = web_client(tmp_path)
    response = client.post(
        "/web/jobs/upload",
        files={"file": ("recording.wav", b"audio", "audio/wav")},
        data={"language": "es"},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["job"]["status"] == "queued"
    assert data["job"]["language"] == "es"
    assert "private-service-secret" not in response.text
    path = f"/web/jobs/{data['job']['id']}"
    assert client.get(path).status_code == 404
    assert client.get(path, headers={"X-Job-Key": data["accessKey"]}).status_code == 200
    assert len(list((tmp_path / "uploads").iterdir())) == 1


def test_public_upload_shares_global_quota_with_url_jobs(tmp_path):
    client = web_client(tmp_path, public_jobs_per_hour=1)
    assert create_job(client).status_code == 202
    assert client.post(
        "/web/jobs/upload", files={"file": ("recording.wav", b"audio")}
    ).status_code == 429
    assert not (tmp_path / "uploads").exists()


def test_public_upload_disabled_and_private_upload_still_protected(tmp_path):
    client = web_client(tmp_path, public_web_enabled=False)
    files = {"file": ("recording.wav", b"audio")}
    assert client.post("/web/jobs/upload", files=files).status_code == 404
    assert client.post("/v1/transcriptions/upload", files=files).status_code == 401


def test_cors_allows_only_configured_frontend(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "VIDEO_TRANSCRIBER_CORS_ORIGINS", "https://transcriber.example.com"
    )
    client = web_client(tmp_path)
    headers = {
        "Origin": "https://transcriber.example.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Job-Key",
    }
    response = client.options("/web/jobs/trn_example", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    headers["Origin"] = "https://untrusted.example.com"
    response = client.options("/web/jobs/trn_example", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_home_serves_browser_interface(tmp_path):
    client = web_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Transcribir vídeo" in response.text
    assert client.get("/v1/transcriptions/trn_example").status_code == 401


def test_public_job_exposes_safe_worker_error(tmp_path):
    from app.models.transcriptions import JobStatus
    from app.services.groq_whisper import GroqAPIError
    from app.workers.job_worker import JobWorker

    class RejectedProcessor:
        def process(self, source_url, requested_language):
            raise GroqAPIError("Groq rechaza la clave de API.")

    client = web_client(tmp_path)
    data = create_job(client).json()
    store = client.app.state.job_store
    JobWorker(store, RejectedProcessor(), 60).process_next()
    response = client.get(f"/web/jobs/{data['job']['id']}",
                          headers={"X-Job-Key": data["accessKey"]})
    assert response.json()["status"] == JobStatus.FAILED
    assert response.json()["errorMessage"] == "Groq rechaza la clave de API."
