import sys

from app import youtube_check
from app.core.config import Settings


def test_diagnostic_checks_audio_and_removes_temporary_download(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["youtube_check", "https://youtu.be/abc", "--audio"],
    )
    monkeypatch.setattr(youtube_check, "Settings", lambda: Settings(
        token="test", _env_file=None,
    ))
    downloads = []

    class Probe:
        def __init__(self, **kwargs):
            pass

        def get_duration_seconds(self, url):
            return 230

    class Audio:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, directory):
            path = directory / "video.m4a"
            path.write_bytes(b"audio")
            downloads.append(path)
            return path

    monkeypatch.setattr(youtube_check, "YtDlpVideoDurationProbe", Probe)
    monkeypatch.setattr(youtube_check, "YtDlpAudioFetcher", Audio)
    assert youtube_check.main() == 0
    assert '"audio_bytes": 5' in capsys.readouterr().out
    assert not downloads[0].exists()


def test_diagnostic_rejects_unallowed_url_before_downloading(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["youtube_check", "https://internal.example"])
    monkeypatch.setattr(youtube_check, "Settings", lambda: Settings(
        token="test", _env_file=None,
    ))

    def unexpected_probe(**kwargs):
        raise AssertionError("Must validate the URL before contacting the provider")

    monkeypatch.setattr(youtube_check, "YtDlpVideoDurationProbe", unexpected_probe)
    assert youtube_check.main() == 1
    assert '"status": "failed"' in capsys.readouterr().out
