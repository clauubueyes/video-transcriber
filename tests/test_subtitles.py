from pathlib import Path
from typing import Any

from app.services.subtitles import YtDlpSubtitleFetcher


class FakeYoutubeDL:
    def __init__(self, options: dict[str, Any], write_subtitle: bool) -> None:
        self.options = options
        self.write_subtitle = write_subtitle
        self.downloaded_url: str | None = None

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        self.downloaded_url = url
        assert download is True
        if self.write_subtitle:
            output_directory = Path(self.options["outtmpl"]).parent
            (output_directory / "video.es.vtt").write_text("WEBVTT\n", encoding="utf-8")
        return {"id": "video"}


def test_fetcher_downloads_only_requested_vtt_subtitles(tmp_path) -> None:
    created: list[FakeYoutubeDL] = []

    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        fake = FakeYoutubeDL(options, write_subtitle=True)
        created.append(fake)
        return fake

    subtitle = YtDlpSubtitleFetcher(factory).fetch(
        "https://www.youtube.com/watch?v=abc",
        "es",
        tmp_path,
    )

    assert subtitle == tmp_path / "video.es.vtt"
    assert created[0].options["skip_download"] is True
    assert created[0].options["subtitleslangs"] == ["es"]


def test_fetcher_returns_none_when_no_subtitle_was_written(tmp_path) -> None:
    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        return FakeYoutubeDL(options, write_subtitle=False)

    subtitle = YtDlpSubtitleFetcher(factory).fetch(
        "https://www.youtube.com/watch?v=abc",
        None,
        tmp_path,
    )

    assert subtitle is None
