from pathlib import Path

import pytest

from app.services.ytdlp import youtube_dl


@pytest.mark.parametrize("fail", [False, True])
def test_cookie_copy_is_writable_and_removed_on_exit(tmp_path, monkeypatch, fail):
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


def test_no_cookies_keeps_anonymous_options(monkeypatch):
    from contextlib import nullcontext

    received = []

    def factory(options):
        received.append(options)
        return nullcontext()

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", factory)
    with youtube_dl({"skip_download": True}):
        pass
    assert received == [{"skip_download": True}]


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
