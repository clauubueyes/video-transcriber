from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.api.routes.transcriptions import (
    get_public_host_validator,
    get_redirect_validator,
    get_video_duration_probe,
)
from app.core.config import Settings
from app.main import create_app


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


def test_home_serves_browser_interface(tmp_path):
    client = web_client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Transcribir vídeo" in response.text
    assert client.get("/v1/transcriptions/trn_example").status_code == 401
