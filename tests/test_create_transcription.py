from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.core.config import Settings
from app.main import create_app


def client_with_settings(tmp_path) -> TestClient:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token",
        allowed_domains="youtube.com,www.youtube.com,youtu.be",
    )
    return TestClient(app)


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
