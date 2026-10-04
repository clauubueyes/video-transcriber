from copy import deepcopy
from unittest.mock import Mock

import pytest
from yt_dlp.utils import DownloadError

from app.services.youtube_metadata import YoutubeMetadataCache, extract_with_metadata


def video_metadata():
    return {
        "id": "abc", "title": "Vídeo", "duration": 60,
        "formats": [{"format_id": "audio", "url": "https://cdn.example/audio",
                     "ext": "m4a", "acodec": "aac", "vcodec": "none"}],
        "subtitles": {}, "automatic_captions": {},
        "chapters": [
            {"start_time": 0, "end_time": 30, "title": "Introducción"},
            {"start_time": 30, "end_time": 60, "title": "Desarrollo"},
        ],
    }


def test_cache_returns_independent_metadata_and_expires():
    now = 0
    cache = YoutubeMetadataCache(ttl_seconds=30, clock=lambda: now)
    metadata = video_metadata()
    cache.put("url", metadata)
    metadata["formats"][0]["url"] = "changed outside"
    first = cache.get("url")
    first["formats"][0]["url"] = "changed by downloader"
    assert cache.get("url")["formats"][0]["url"] == "https://cdn.example/audio"
    now = 30
    assert cache.get("url") is None
    assert cache._size_bytes == 0


def test_cache_bounds_bytes_and_evicts_least_recently_used_entries():
    cache = YoutubeMetadataCache(max_entries=2, max_bytes=2000)
    cache.put("first", video_metadata())
    cache.put("second", video_metadata())
    assert cache.get("first") is not None
    cache.put("third", video_metadata())
    assert cache.get("second") is None
    assert cache.get("first") is not None
    assert cache.get("third") is not None
    large = video_metadata()
    large["formats"][0]["url"] = "x" * 3000
    cache.put("too-large", large)
    assert cache.get("too-large") is None
    assert cache.get("first") is not None
    assert cache._size_bytes <= 2000


def test_cache_evicts_to_fit_byte_budget():
    cache = YoutubeMetadataCache(max_entries=10, max_bytes=1500)
    metadata = video_metadata()
    metadata["title"] = "x" * 500
    cache.put("first", metadata)
    cache.put("second", metadata)
    assert cache.get("first") is None
    assert cache.get("second") is not None
    assert cache._size_bytes <= 1500


def test_cache_drops_unneeded_large_fields_and_download_selections():
    metadata = video_metadata()
    metadata["comments"] = "x" * 10_000
    metadata["description"] = "x" * 10_000
    metadata["requested_formats"] = [{"vcodec": "h264"}]
    metadata["requested_subtitles"] = {"es": {"url": "old"}}
    cache = YoutubeMetadataCache(max_bytes=1000)
    cache.put("url", metadata)
    cached = cache.get("url")
    assert cached is not None
    for key in ("comments", "description", "requested_formats", "requested_subtitles"):
        assert key not in cached


def test_parallel_requests_for_same_video_share_one_extraction():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from time import sleep

    cache = YoutubeMetadataCache()
    barrier = Barrier(4)
    calls = []

    def loader():
        calls.append(True)
        sleep(0.02)
        return video_metadata()

    def load(_):
        barrier.wait(timeout=2)
        return cache.get_or_load("url", loader)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(load, range(4)))
    assert len(calls) == 1
    assert all(result["duration"] == 60 for result in results)
    assert len({id(result) for result in results}) == 4


def test_expired_media_url_refreshes_once_before_download():
    cache = YoutubeMetadataCache()
    cache.put("url", video_metadata())
    provider = Mock()
    provider.extract_info.return_value = video_metadata()
    provider.process_ie_result.side_effect = [
        DownloadError("HTTP Error 403: expired media URL"), {"id": "downloaded"},
    ]
    result = extract_with_metadata(provider, "url", download=True, cache=cache)
    assert result == {"id": "downloaded"}
    provider.extract_info.assert_called_once_with("url", download=False)
    assert provider.process_ie_result.call_count == 2


def test_failed_refresh_does_not_loop():
    cache = YoutubeMetadataCache()
    cache.put("url", video_metadata())
    provider = Mock()
    provider.extract_info.return_value = video_metadata()
    provider.process_ie_result.side_effect = DownloadError("HTTP Error 403")
    with pytest.raises(DownloadError):
        extract_with_metadata(provider, "url", download=True, cache=cache)
    assert provider.process_ie_result.call_count == 2
    provider.extract_info.assert_called_once()


def test_rate_limit_is_not_retried():
    cache = YoutubeMetadataCache()
    cache.put("url", video_metadata())
    provider = Mock()
    provider.process_ie_result.side_effect = DownloadError("HTTP Error 429")
    with pytest.raises(DownloadError):
        extract_with_metadata(provider, "url", download=True, cache=cache)
    provider.extract_info.assert_not_called()


@pytest.mark.parametrize("subtitles", [False, True])
def test_cached_metadata_downloads_audio_or_subtitles_with_real_ytdlp(
    tmp_path, subtitles,
):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    from unittest.mock import patch

    from app.services.audio import YtDlpAudioFetcher
    from app.services.subtitles import YtDlpSubtitleFetcher
    from app.services.youtube_metadata import YoutubeDL

    requested_paths = []
    audio_bytes = (b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHola\n"
                   if subtitles else b"synthetic audio" * 1000)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested_paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(audio_bytes)))
            self.end_headers()
            self.wfile.write(audio_bytes)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source_url = "https://www.youtube.com/watch?v=abc"
    metadata = video_metadata()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    metadata["formats"][0]["url"] = endpoint + "/audio.m4a"
    # La consulta de duración pudo haber seleccionado vídeo como formato inicial.
    metadata["formats"].append({
        "format_id": "video", "url": endpoint + "/video.mp4", "ext": "mp4",
        "vcodec": "h264", "acodec": "aac", "height": 1080,
    })
    metadata.update({"url": endpoint + "/video.mp4", "ext": "mp4",
                     "vcodec": "h264", "acodec": "aac"})
    if subtitles:
        metadata["subtitles"] = {"es": [{"ext": "vtt",
                                          "url": endpoint + "/captions.vtt"}]}
    cache = YoutubeMetadataCache()
    cache.put(source_url, metadata)
    try:
        with patch.object(YoutubeDL, "extract_info",
                   side_effect=AssertionError("No debería repetir la extracción")):
            if subtitles:
                path = YtDlpSubtitleFetcher(metadata_cache=cache).fetch(
                    source_url, "es", tmp_path,
                )
            else:
                path = YtDlpAudioFetcher(metadata_cache=cache).fetch(
                    source_url, tmp_path,
                )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert path.name == ("abc.es.vtt" if subtitles else "abc.m4a")
    assert path.read_bytes() == audio_bytes
    assert requested_paths == (["/captions.vtt"] if subtitles else ["/audio.m4a"])


@pytest.mark.parametrize("has_subtitles", [True, False])
def test_api_validation_subtitles_and_audio_share_one_extraction(
    tmp_path, monkeypatch, has_subtitles,
):
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app.api.dependencies import get_settings
    from app.api.routes.transcriptions import (
        get_public_host_validator,
        get_redirect_validator,
    )
    from app.core.config import Settings
    from app.main import create_app
    from app.models.transcriptions import Segment
    from app.workers.job_worker import TranscriptionResult

    counts = {"extract": 0, "subtitles": 0, "audio": 0}

    class Provider:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert not download
            counts["extract"] += 1
            metadata = deepcopy(video_metadata())
            if has_subtitles:
                metadata["subtitles"] = {"es": [{"ext": "vtt", "url": "caption"}]}
            return metadata

        def process_ie_result(self, info, download):
            assert download
            directory = Path(self.options["outtmpl"]).parent
            if self.options.get("writesubtitles"):
                counts["subtitles"] += 1
                if has_subtitles:
                    (directory / "video.es.vtt").write_text(
                        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSubtítulo\n",
                        encoding="utf-8",
                    )
            else:
                assert self.options["format"] == "bestaudio/best"
                counts["audio"] += 1
                (directory / "video.m4a").write_bytes(b"synthetic audio")
            return info

    def transcribe(self, audio, language):
        assert audio.read_bytes() == b"synthetic audio"
        return TranscriptionResult(
            language=language, duration_seconds=1, text="Audio",
            segments=[Segment(start=0, end=1, text="Audio")],
        )

    monkeypatch.setattr("app.services.ytdlp.YoutubeDL", Provider)
    monkeypatch.setattr("app.services.whisper.FasterWhisperTranscriber.transcribe",
                        transcribe)
    app = create_app(tmp_path / "jobs.sqlite3")
    app.dependency_overrides[get_settings] = lambda: Settings(
        token="test-token", groq_api_key=None, _env_file=None,
    )
    app.dependency_overrides[get_public_host_validator] = lambda: lambda host: None
    app.dependency_overrides[get_redirect_validator] = lambda: lambda url: url
    response = TestClient(app).post("/v1/transcriptions", json={
        "source": {"type": "url", "url": "https://youtu.be/abc"}, "language": "es",
    }, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 202
    job = app.state.job_store.get(response.json()["id"])
    assert job.status.value == "completed"
    assert job.text == ("Subtítulo" if has_subtitles else "Audio")
    assert [chapter.title for chapter in job.chapters] == [
        "Introducción", "Desarrollo",
    ]
    result = TestClient(app).get(
        f"/v1/transcriptions/{job.id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert result.json()["chapters"] == [
        {"start": 0, "end": 30, "title": "Introducción"},
        {"start": 30, "end": 60, "title": "Desarrollo"},
    ]
    assert counts == {"extract": 1, "subtitles": int(has_subtitles),
                      "audio": int(not has_subtitles)}
