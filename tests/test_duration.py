from typing import Any

from app.services.duration import YtDlpVideoDurationProbe


class FakeYoutubeDL:
    def __init__(self, options: dict[str, Any], duration: float | None) -> None:
        self.options = options
        self.duration = duration

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        assert url == "https://www.youtube.com/watch?v=abc"
        assert download is False
        return {"duration": self.duration}


def test_probe_reads_duration_without_downloading_content() -> None:
    created: list[FakeYoutubeDL] = []

    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        fake = FakeYoutubeDL(options, duration=482)
        created.append(fake)
        return fake

    duration = YtDlpVideoDurationProbe(factory).get_duration_seconds(
        "https://www.youtube.com/watch?v=abc"
    )

    assert duration == 482
    assert created[0].options["skip_download"] is True
    assert created[0].options["noplaylist"] is True


def test_probe_returns_none_when_provider_has_no_duration() -> None:
    def factory(options: dict[str, Any]) -> FakeYoutubeDL:
        return FakeYoutubeDL(options, duration=None)

    duration = YtDlpVideoDurationProbe(factory).get_duration_seconds(
        "https://www.youtube.com/watch?v=abc"
    )

    assert duration is None
