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
