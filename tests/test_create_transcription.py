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
