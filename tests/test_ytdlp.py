from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ytdlp import youtube_dl, youtube_download_options


@pytest.mark.parametrize("fail", [False, True])
def test_cookie_copy_is_writable_and_removed_on_exit(
    tmp_path, monkeypatch, caplog, fail,
):
    caplog.set_level("INFO", logger="video_transcriber.ytdlp")
    original = tmp_path / "youtube-cookies.txt"
    original.write_text("original", encoding="utf-8")
    copies = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.path = Path(options["cookiefile"])
            copies.append(self.path)

        def __enter__(self):
            assert self.path.read_text(encoding="utf-8") == "original"
            return self

        def __exit__(self, *args):
            self.path.write_text("updated", encoding="utf-8")

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", FakeYoutubeDL)
    if fail:
        with pytest.raises(RuntimeError):
            with youtube_dl({}, original):
                raise RuntimeError("provider failed")
    else:
        with youtube_dl({}, original):
            pass

    assert original.read_text(encoding="utf-8") == "original"
    assert not copies[0].exists()
    assert "youtube_cookie_file_loaded" in caplog.text
    assert "original" not in caplog.text


def test_no_cookies_keeps_anonymous_options(monkeypatch, caplog):
    from contextlib import nullcontext

    received = []
    caplog.set_level("INFO", logger="video_transcriber.ytdlp")

    def factory(options):
        received.append(options)
        return nullcontext()

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", factory)
    with youtube_dl({"skip_download": True}):
        pass
    assert received == [{"skip_download": True}]
    assert "youtube_cookie_file_not_configured" in caplog.text


def test_missing_cookie_file_uses_anonymous_options(tmp_path, monkeypatch, caplog):
    from contextlib import nullcontext

    received = []
    options = {"skip_download": True}

    def factory(ydl_options):
        received.append(ydl_options)
        return nullcontext()

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", factory)
    with youtube_dl(options, tmp_path / "missing-cookies.txt"):
        pass

    assert received == [{"skip_download": True}]
    assert options == {"skip_download": True}
    assert "youtube_cookie_file_missing" in caplog.text
    assert "VIDEO_TRANSCRIBER_YOUTUBE_COOKIE_FILE" in caplog.text


def test_unreadable_cookie_file_logs_and_preserves_error(tmp_path, monkeypatch, caplog):
    def deny_copy(source, destination):
        raise PermissionError("cookie file is not readable")

    def unexpected_provider(options):
        pytest.fail("yt-dlp must not run after a cookie read error")

    monkeypatch.setattr("app.services.ytdlp.copyfile", deny_copy)
    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", unexpected_provider)
    with pytest.raises(PermissionError, match="cookie file is not readable"):
        with youtube_dl({}, tmp_path / "cookies.txt"):
            pass

    assert "youtube_cookie_file_unreadable" in caplog.text


def test_provider_file_error_is_not_retried_without_cookies(tmp_path, monkeypatch):
    from contextlib import nullcontext

    original = tmp_path / "youtube-cookies.txt"
    original.write_text("original", encoding="utf-8")
    received = []

    def factory(options):
        received.append(options)
        return nullcontext()

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", factory)
    with pytest.raises(FileNotFoundError, match="provider file missing"):
        with youtube_dl({}, original):
            raise FileNotFoundError("provider file missing")

    assert len(received) == 1
    assert "cookiefile" in received[0]


def test_provider_logging_redacts_proxy_and_reports_token_request(tmp_path, caplog):
    caplog.set_level("INFO", logger="video_transcriber.ytdlp")
    proxy = "http://user:private-password@proxy.example:8080"
    settings = Settings(
        token="test", _env_file=None, youtube_player_clients=" mweb, tv,web_safari ",
        youtube_po_token_server_home=tmp_path, youtube_proxy_url=proxy,
    )
    options = youtube_download_options(settings)

    assert options["proxy"] == proxy
    assert options["extractor_args"]["youtube"]["player_client"] == [
        "mweb", "tv", "web_safari",
    ]
    assert options["extractor_args"]["youtubepot-bgutilscript"] == {
        "server_home": [str(tmp_path)],
    }
    options["logger"].warning(f"Proxy failed: {proxy}")
    options["logger"].error("Failed: https://other:another-secret@proxy.example")
    options["logger"].debug(
        "Generating a gvs PO Token for mweb client via bgutil script",
    )
    options["logger"].debug("[debug] Generated POT: secret-token")

    assert "youtube_po_token_requested" in caplog.text
    for secret in ("private-password", "another-secret", "secret-token"):
        assert secret not in caplog.text


def test_proxy_credentials_are_redacted_in_provider_exception(monkeypatch):
    from contextlib import nullcontext

    from yt_dlp.utils import DownloadError

    proxy = "http://user:private-password@proxy.example:8080"
    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", lambda opts: nullcontext())
    with pytest.raises(DownloadError) as caught:
        with youtube_dl({"proxy": proxy}):
            raise DownloadError(f"Connection failed: {proxy}")

    assert "private-password" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_browser_profile_uses_ytdlp_impersonation_target():
    from yt_dlp.networking.impersonate import ImpersonateTarget

    options = youtube_download_options(Settings(
        token="test", _env_file=None, youtube_impersonate="chrome",
    ))
    assert options["impersonate"] == ImpersonateTarget(client="chrome")


@pytest.mark.parametrize("operation", ["metadata", "audio", "subtitles"])
def test_access_options_reach_all_youtube_operations(operation, tmp_path, monkeypatch):
    from app.services.audio import YtDlpAudioFetcher
    from app.services.duration import YtDlpVideoDurationProbe
    from app.services.subtitles import YtDlpSubtitleFetcher

    options = youtube_download_options(Settings(
        token="test", _env_file=None, youtube_player_clients="mweb,tv,web_safari",
        youtube_po_token_server_home=tmp_path,
        youtube_proxy_url="http://user:secret@proxy.example:8080",
    ))
    received = []

    class FakeProvider:
        def __init__(self, opts):
            received.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            if operation == "audio":
                (tmp_path / "video.m4a").write_bytes(b"audio")
            return {"duration": 230}

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", FakeProvider)
    url = "https://www.youtube.com/watch?v=abc"
    if operation == "metadata":
        assert YtDlpVideoDurationProbe(download_options=options).get_duration_seconds(
            url,
        ) == 230
    elif operation == "audio":
        YtDlpAudioFetcher(download_options=options).fetch(url, tmp_path)
    else:
        YtDlpSubtitleFetcher(download_options=options).fetch(url, "es", tmp_path)

    for name in ("proxy", "extractor_args", "logger"):
        assert received[0][name] == options[name]
