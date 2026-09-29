from app.core.config import Settings


def test_settings_normalizes_allowed_domains() -> None:
    settings = Settings(
        token="test-token",
        allowed_domains=" YouTube.com, youtu.be, youtube.com ",
    )

    assert settings.allowed_domain_set == frozenset({"youtube.com", "youtu.be"})


def test_settings_requires_a_service_token() -> None:
    try:
        Settings(_env_file=None)
    except ValueError as error:
        assert "token" in str(error)
    else:
        raise AssertionError("Settings debe exigir VIDEO_TRANSCRIBER_TOKEN")


def test_settings_allows_local_whisper_runtime_configuration(tmp_path) -> None:
    model_path = tmp_path / "whisper-small"
    settings = Settings(
        token="test-token",
        model_path=model_path,
        whisper_device="cuda",
        whisper_compute_type="float16",
    )

    assert settings.model_path == model_path
    assert settings.whisper_device == "cuda"
    assert settings.whisper_compute_type == "float16"
