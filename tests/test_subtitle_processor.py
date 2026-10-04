from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from app.models.transcriptions import Chapter, Segment
from app.services.subtitle_processor import SubtitleFirstProcessor
from app.workers.job_worker import TranscriptionResult


class SubtitleFetcherWithContent:
    def fetch(
        self,
        source_url: str,
        language: str | None,
        temporary_directory: Path,
    ) -> Path:
        subtitle_path = temporary_directory / "video.es.vtt"
        subtitle_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHola\n",
            encoding="utf-8",
        )
        return subtitle_path


class NoSubtitleFetcher:
    def fetch(
        self,
        source_url: str,
        language: str | None,
        temporary_directory: Path,
    ) -> None:
        return None


class RecordingFallback:
    def __init__(self) -> None:
        self.calls = 0

    def process(
        self,
        source_url: str,
        requested_language: str | None,
    ) -> TranscriptionResult:
        self.calls += 1
        return TranscriptionResult(
            language=requested_language,
            duration_seconds=1,
            text="Audio",
            segments=[Segment(start=0, end=1, text="Audio")],
        )


def test_processor_uses_available_subtitles_before_audio_fallback() -> None:
    fallback = RecordingFallback()
    processor = SubtitleFirstProcessor(SubtitleFetcherWithContent(), fallback)

    result = processor.process("https://www.youtube.com/watch?v=abc", "es")

    assert result.text == "Hola"
    assert result.segments == [Segment(start=0, end=2, text="Hola")]
    assert fallback.calls == 0


def test_processor_uses_audio_fallback_without_subtitles() -> None:
    fallback = RecordingFallback()
    processor = SubtitleFirstProcessor(NoSubtitleFetcher(), fallback)

    result = processor.process("https://www.youtube.com/watch?v=abc", "es")

    assert result.text == "Audio"
    assert fallback.calls == 1


def test_subtitle_provider_failure_still_transcribes_audio(caplog):
    class BlockedSubtitles:
        def fetch(self, *args):
            raise DownloadError("Unable to download subtitles: HTTP Error 403")

    fallback = RecordingFallback()
    result = SubtitleFirstProcessor(BlockedSubtitles(), fallback).process(
        "https://www.youtube.com/watch?v=abc", "es",
    )

    assert result.text == "Audio"
    assert fallback.calls == 1
    assert "youtube_subtitles_failed" in caplog.text


def test_unexpected_subtitle_failure_is_not_hidden():
    class BrokenSubtitles:
        def fetch(self, *args):
            raise OSError("disk full")

    fallback = RecordingFallback()
    with pytest.raises(OSError, match="disk full"):
        SubtitleFirstProcessor(BrokenSubtitles(), fallback).process(
            "https://www.youtube.com/watch?v=abc", "es",
        )
    assert fallback.calls == 0


@pytest.mark.parametrize("subtitles", [True, False])
def test_chapters_are_captured_before_processing_even_if_cache_expires(subtitles):
    from app.services.chapters import YtDlpChapterFetcher
    from app.services.youtube_metadata import YoutubeMetadataCache

    now = 0
    cache = YoutubeMetadataCache(ttl_seconds=1, clock=lambda: now)
    cache.put("url", {
        "id": "abc", "formats": [{"format_id": "audio"}], "duration": 10,
        "chapters": [{"start_time": 0, "end_time": 10, "title": "Introducción"}],
    })

    class ExpiringFetcher:
        def fetch(self, *args):
            nonlocal now
            now = 2
            if subtitles:
                return SubtitleFetcherWithContent().fetch(*args)
            return None

    processor = SubtitleFirstProcessor(
        ExpiringFetcher(), RecordingFallback(),
        chapter_fetcher=YtDlpChapterFetcher(metadata_cache=cache),
    )
    result = processor.process("url", "es")
    assert result.chapters == [Chapter(start=0, end=10, title="Introducción")]
    assert cache.get("url") is None


def test_chapter_extraction_failure_still_returns_transcription():
    class UnavailableChapters:
        def fetch(self, source_url):
            raise DownloadError("No hay metadatos disponibles")

    fallback = RecordingFallback()
    result = SubtitleFirstProcessor(
        SubtitleFetcherWithContent(), fallback,
        chapter_fetcher=UnavailableChapters(),
    ).process("url", "es")
    assert result.text == "Hola"
    assert result.chapters == []
    assert fallback.calls == 0
