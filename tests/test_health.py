from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_available_service() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_available_job_storage() -> None:
    client = TestClient(create_app())

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_reports_unavailable_job_storage(tmp_path) -> None:
    app = create_app(tmp_path / "jobs.sqlite3")
    app.state.job_store.close()
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
