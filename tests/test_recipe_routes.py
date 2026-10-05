from datetime import UTC, datetime, timedelta
from threading import Lock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.api.routes.recipes import get_recipe_extractor
from app.api.routes.web import access_key
from app.core.config import Settings
from app.main import create_app
from app.models.recipes import ExtractedRecipe
from app.models.transcriptions import JobStatus
from app.services.recipe_extractor import RecipeExtractionError
from app.storage.jobs import SqliteJobStore


def complete_job(store):
    job = store.create("https://youtu.be/recipe", "es")
    store.update_status(job.id, JobStatus.DOWNLOADING)
    store.update_status(job.id, JobStatus.TRANSCRIBING)
    store.complete(
        job.id, language="es", duration_seconds=600,
        text="Para la tortilla, batimos 2 huevos con sal y cuajamos en una sartén.",
        segments=[], expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return job


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(
        token="private-token", groq_api_key="private-provider-key", _env_file=None,
    )
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: settings
    job = complete_job(app.state.job_store)
    recipe = ExtractedRecipe.model_validate({
        "recipeFound": True, "title": "Tortilla", "description": "Tortilla sencilla.",
        "ingredients": [{"item": "Huevos", "amount": "2"},
                        {"item": "Sal", "amount": ""}],
        "steps": [{"order": 1, "instruction": "Batir y cuajar los huevos."}],
        "tags": [], "prepTimeMinutes": None, "servings": None,
        "notes": ["La cantidad de sal no se menciona."],
    })
    extractor = Mock()
    extractor.extract.return_value = recipe
    monkeypatch.setattr(
        "app.api.routes.recipes.get_recipe_extractor", lambda settings: extractor,
    )
    yield TestClient(app), settings, job, extractor
    app.state.job_store.close()


def post_recipe(client, settings, job, key=None):
    return client.post(
        f"/web/jobs/{job.id}/recipe",
        headers={"X-Job-Key": key or access_key(job.id, settings)},
    )


def test_extracts_and_reuses_persistent_result_without_another_provider_call(setup):
    client, settings, job, extractor = setup
    response = post_recipe(client, settings, job)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["ingredients"][0] == {"item": "Huevos", "amount": "2"}
    assert "private" not in response.text
    assert post_recipe(client, settings, job).json() == response.json()
    extractor.extract.assert_called_once()
    reopened = SqliteJobStore(client.app.state.job_store._connection.execute(
        "PRAGMA database_list",
    ).fetchone()[2])
    try:
        assert reopened.get_recipe(job.id) == response.json()
    finally:
        reopened.close()


def test_wrong_or_missing_key_never_reaches_the_provider(setup):
    client, settings, job, extractor = setup
    path = f"/web/jobs/{job.id}/recipe"
    assert client.post(path).status_code == 404
    assert post_recipe(client, settings, job, "wrong-key").status_code == 404
    other = complete_job(client.app.state.job_store)
    assert post_recipe(
        client, settings, other, access_key(job.id, settings),
    ).status_code == 404
    extractor.extract.assert_not_called()


def test_queued_or_expired_jobs_cannot_be_extracted(setup):
    client, settings, job, extractor = setup
    queued = client.app.state.job_store.create("https://youtu.be/queued", "es")
    assert post_recipe(client, settings, queued).status_code == 409
    client.app.state.job_store.expire_due_results(datetime.now(UTC) + timedelta(days=1))
    assert post_recipe(client, settings, job).status_code == 409
    extractor.extract.assert_not_called()


def test_disabled_public_web_or_extraction_blocks_provider_calls(setup):
    client, settings, job, extractor = setup
    settings.recipe_extraction_enabled = False
    assert post_recipe(client, settings, job).status_code == 404
    settings.recipe_extraction_enabled = True
    settings.public_web_enabled = False
    assert post_recipe(client, settings, job).status_code == 404
    extractor.extract.assert_not_called()


def test_provider_failure_preserves_transcript_for_retry(setup):
    client, settings, job, extractor = setup
    extractor.extract.side_effect = RecipeExtractionError("Cuota de Groq agotada.", 429)
    assert post_recipe(client, settings, job).status_code == 429
    assert client.app.state.job_store.get(job.id).text is not None
    assert client.app.state.job_store.get_recipe(job.id) is None
    extractor.extract.side_effect = None
    assert post_recipe(client, settings, job).status_code == 200


def test_oversized_transcripts_are_rejected_before_model_access(setup):
    client, settings, job, extractor = setup
    settings.recipe_max_transcript_chars = 5
    assert post_recipe(client, settings, job).status_code == 422
    extractor.extract.assert_not_called()


def test_cached_extractions_expire_and_delete_with_the_transcript(setup):
    client, settings, job, _ = setup
    assert post_recipe(client, settings, job).status_code == 200
    store = client.app.state.job_store
    store.expire_due_results(datetime.now(UTC) + timedelta(days=1))
    assert store.get_recipe(job.id) is None
    assert store._connection.execute(
        "SELECT recipe_json FROM transcription_jobs WHERE id = ?", (job.id,),
    ).fetchone()[0] is None
    assert not store.save_recipe(job.id, {"shouldNot": "revive expired job"})
    second = complete_job(store)
    assert post_recipe(client, settings, second).status_code == 200
    store.delete(second.id)
    assert store.get_recipe(second.id) is None
    assert not store.save_recipe(second.id, {})


def test_limits_new_extractions_but_allows_cached_recipes(setup):
    client, settings, job, extractor = setup
    settings.recipe_jobs_per_hour = 1
    assert post_recipe(client, settings, job).status_code == 200
    assert post_recipe(client, settings, job).status_code == 200
    other = complete_job(client.app.state.job_store)
    assert post_recipe(client, settings, other).status_code == 429
    extractor.extract.assert_called_once()


def test_rejects_parallel_model_calls_and_releases_gate_after_failure(setup):
    client, settings, job, extractor = setup
    post_recipe(client, settings, job)
    other = complete_job(client.app.state.job_store)
    gate: Lock = client.app.state.recipe_gate
    gate.acquire()
    try:
        assert post_recipe(client, settings, other).status_code == 503
    finally:
        gate.release()
    extractor.extract.side_effect = RecipeExtractionError("Proveedor caído.")
    assert post_recipe(client, settings, other).status_code == 502
    assert not gate.locked()


def test_missing_credentials_have_a_clear_configuration_error():
    settings = Settings(token="token", _env_file=None)
    with pytest.raises(Exception) as raised:
        get_recipe_extractor(settings)
    assert raised.value.status_code == 503
    assert "VIDEO_TRANSCRIBER_GROQ_API_KEY" in raised.value.detail


def test_dedicated_recipe_key_takes_precedence_over_whisper_key():
    settings = Settings(
        token="token", recipe_api_key="recipe-secret", groq_api_key="audio-secret",
        _env_file=None,
    )
    extractor = get_recipe_extractor(settings)
    assert extractor._api_key == "recipe-secret"
    assert extractor._model == "openai/gpt-oss-20b"
