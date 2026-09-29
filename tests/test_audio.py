from pathlib import Path
from typing import Any

import pytest

from app.services.audio import AudioNotFoundError, YtDlpAudioFetcher


class FakeYoutubeDL:
    def __init__(self, options: dict[str, Any], write_audio: bool) -> None:
        self.options = options
        self.write_audio = write_audio

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        assert url == "https://www.youtube.com/watch?v=abc"
        assert download is True
        if self.write_audio:
            output_directory = Path(self.options["outtmpl"]).parent
            (output_directory / "video.m4a").write_bytes(b"audio")
        return {"id": "video"}


def test_fetcher_downloads_audio_only(tmp_path) -> None:
    created: list[FakeYoutubeDL] = []

    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        fake = FakeYoutubeDL(options, write_audio=True)
        created.append(fake)
        return fake

    audio = YtDlpAudioFetcher(factory).fetch(
        "https://www.youtube.com/watch?v=abc", tmp_path
    )

    assert audio == tmp_path / "video.m4a"
    assert created[0].options["format"] == "bestaudio/best"
    assert created[0].options["noplaylist"] is True


def test_fetcher_rejects_missing_audio(tmp_path) -> None:
    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        return FakeYoutubeDL(options, write_audio=False)

    with pytest.raises(AudioNotFoundError, match="obtener el audio"):
        YtDlpAudioFetcher(factory).fetch(
            "https://www.youtube.com/watch?v=abc", tmp_path
        )
