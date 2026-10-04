from unittest.mock import Mock

import pytest

from app.models.transcriptions import Chapter
from app.services.chapters import YtDlpChapterFetcher, parse_chapters
from app.services.youtube_metadata import YoutubeMetadataCache


def test_chapters_are_sorted_deduplicated_and_bounded():
    chapters = parse_chapters({
        "duration": 90,
        "chapters": [
            {"start_time": 30, "end_time": 120, "title": " Desarrollo "},
            {"start_time": 0, "end_time": 40, "title": "Introducción"},
            {"start_time": 30, "end_time": 60, "title": "Duplicado"},
            {"start_time": 60, "title": "Cierre"},
        ],
    })
    assert chapters == [
        Chapter(start=0, end=30, title="Introducción"),
        Chapter(start=30, end=60, title="Desarrollo"),
        Chapter(start=60, end=90, title="Cierre"),
    ]


@pytest.mark.parametrize("raw", [
    None, "capítulo", {},
    {"start_time": -1, "end_time": 10, "title": "Negativo"},
    {"start_time": True, "end_time": 10, "title": "Booleano"},
    {"start_time": float("nan"), "end_time": 10, "title": "NaN"},
    {"start_time": float("inf"), "end_time": 10, "title": "Infinito"},
    {"start_time": 0, "end_time": 0, "title": "Vacío"},
    {"start_time": 0, "end_time": 10, "title": "  "},
    {"start_time": 20, "end_time": 30, "title": "Fuera de duración"},
])
def test_invalid_chapters_do_not_break_transcription(raw):
    assert parse_chapters({"duration": 20, "chapters": [raw]}) == []


def test_missing_chapters_do_not_create_sections():
    assert parse_chapters({"duration": 90}) == []
    assert parse_chapters({"chapters": "invalid"}) == []
    assert parse_chapters({
        "chapters": [{"start_time": 0, "title": "Sin final conocido"}],
    }) == []


def test_cached_chapters_need_no_additional_youtube_extraction():
    cache = YoutubeMetadataCache()
    cache.put("url", {
        "id": "abc", "duration": 10, "formats": [{"format_id": "audio"}],
        "chapters": [{"start_time": 0, "end_time": 10, "title": "Introducción"}],
    })
    factory = Mock(side_effect=AssertionError("No debe consultar YouTube"))
    chapters = YtDlpChapterFetcher(metadata_cache=cache, ydl_factory=factory).fetch(
        "url",
    )
    assert chapters == [Chapter(start=0, end=10, title="Introducción")]
    factory.assert_not_called()


def test_uncached_chapters_extract_metadata_without_downloading():
    cache = YoutubeMetadataCache()
    provider = Mock()
    provider.extract_info.return_value = {
        "id": "abc", "duration": 10, "formats": [{"format_id": "audio"}],
        "chapters": [{"start_time": 0, "end_time": 10, "title": "Introducción"}],
    }
    context = Mock()
    context.__enter__ = Mock(return_value=provider)
    context.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=context)
    result = YtDlpChapterFetcher(metadata_cache=cache, ydl_factory=factory).fetch(
        "url",
    )
    assert result == [Chapter(start=0, end=10, title="Introducción")]
    provider.extract_info.assert_called_once_with("url", download=False)
    assert factory.call_args.args[0]["skip_download"] is True
    assert cache.get("url")["chapters"][0]["title"] == "Introducción"
