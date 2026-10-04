"""Pruebas unitarias del adaptador de Groq Whisper API."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest

from app.models.transcriptions import ProcessingMethod
from app.services.groq_whisper import (
    GroqAPIError,
    GroqWhisperTranscriber,
    StreamingMultipart,
)


def test_groq_whisper_transcribe_success(tmp_path: Path):
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake audio data")

    fake_response = {
        "text": "Hola mundo desde Groq API",
        "language": "es",
        "duration": 5.0,
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "Hola mundo"},
            {"start": 2.5, "end": 5.0, "text": "desde Groq API"},
        ],
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        transcriber = GroqWhisperTranscriber(api_key="gsk_test_key")
        result = transcriber.transcribe(audio_file, requested_language="es")

    assert result.text == "Hola mundo desde Groq API"
    assert result.language == "es"
    assert result.duration_seconds == 5.0
    assert result.processing_method == ProcessingMethod.GROQ
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hola mundo"
    assert result.segments[1].end == 5.0


def test_groq_whisper_transcribe_file_not_found(tmp_path: Path):
    transcriber = GroqWhisperTranscriber(api_key="gsk_test_key")
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe(tmp_path / "nonexistent.mp3", requested_language=None)


def test_groq_auth_error_is_safe_and_request_has_user_agent(tmp_path):
    from io import BytesIO
    from urllib.error import HTTPError

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"audio")
    error = HTTPError("https://api.groq.com", 401, "Unauthorized", {},
                      BytesIO(b"private provider response"))
    with patch("urllib.request.urlopen", side_effect=error) as request:
        with pytest.raises(GroqAPIError, match="Groq rechaza la clave") as caught:
            GroqWhisperTranscriber("secret").transcribe(audio, None)
    assert "private provider response" not in str(caught.value)
    assert (
        request.call_args.args[0].get_header("User-agent") == "video-transcriber/0.1.0"
    )


def test_multipart_stream_limits_audio_reads_and_is_repeatable(tmp_path):
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"a" * 200_000)
    body = StreamingMultipart(b"prefix", audio, b"suffix")

    for _ in range(2):
        blocks = list(body)
        assert max(map(len, blocks)) <= 64 * 1024
        assert sum(map(len, blocks)) == body.content_length
        assert b"".join(blocks) == b"prefix" + b"a" * 200_000 + b"suffix"


def test_streamed_request_works_over_http_with_content_length(tmp_path):
    """Comprueba urllib/http.client reales, sin enviar datos a un proveedor."""
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"synthetic audio" * 12_000)
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received["length"] = int(self.headers["Content-Length"])
            received["transfer_encoding"] = self.headers.get("Transfer-Encoding")
            received["body"] = self.rfile.read(received["length"])
            payload = json.dumps({"text": "Hola", "duration": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/transcriptions"
        result = GroqWhisperTranscriber(
            "test-key", endpoint=endpoint, timeout_seconds=2,
        ).transcribe(audio, "es")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.text == "Hola"
    assert received["transfer_encoding"] is None
    assert len(received["body"]) == received["length"]
    assert b"synthetic audio" * 12_000 in received["body"]
    assert b'name="language"\r\n\r\nes\r\n' in received["body"]
    assert b"Bearer test-key" not in received["body"]


def test_large_audio_is_processed_sequentially_with_global_timestamps(tmp_path):
    from types import SimpleNamespace

    audio = tmp_path / "long.wav"
    with audio.open("wb") as source:
        source.truncate(25_000_001)
    conversions = []
    uploaded = []

    def run(command, **kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="125\n")
        target = Path(command[-1])
        assert not target.exists()
        assert command[command.index("-ar") + 1] == "16000"
        assert command[command.index("-ac") + 1] == "1"
        assert command[command.index("-c:a") + 1] == "flac"
        conversions.append((float(command[command.index("-ss") + 1]),
                            float(command[command.index("-t") + 1])))
        target.write_bytes(b"prepared audio")
        return SimpleNamespace(returncode=0)

    def upload(request, **kwargs):
        body = b"".join(request.data)
        uploaded.append(body)
        assert b"prepared audio" in body
        assert b'name="language"' not in body
        index = len(uploaded) - 1
        payload = {
            "language": "Spanish", "duration": 62,
            "segments": [
                {"start": 0, "end": 0.5, "text": "Solape"},
                {"start": 1, "end": 2, "text": f"Parte {index}"},
            ],
        }
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode()
        return response

    with (
        patch("app.services.groq_whisper.subprocess.run", side_effect=run),
        patch("urllib.request.urlopen", side_effect=upload),
    ):
        result = GroqWhisperTranscriber(
            "test-key", chunk_seconds=60,
        ).transcribe(audio, None)

    assert conversions == [(0, 61), (59, 62), (119, 6)]
    assert len(uploaded) == 3
    assert result.duration_seconds == 125
    assert result.processing_method == ProcessingMethod.GROQ
    assert result.language == "Spanish"
    assert result.text == "Solape Parte 0 Parte 1 Parte 2"
    assert [segment.start for segment in result.segments] == [0, 1, 60, 120]
    assert [segment.end for segment in result.segments] == [0.5, 2, 61, 121]
    assert not list(tmp_path.glob("*.flac"))


@pytest.mark.parametrize("extension", [".mp3", ".m4a", ".mp4", ".webm"])
def test_small_supported_files_are_sent_without_ffmpeg(tmp_path, extension):
    audio = tmp_path / f"small{extension}"
    audio.write_bytes(b"synthetic audio")
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"text": "Hola", "duration": 1}'
    with (
        patch("urllib.request.urlopen", return_value=response) as upload,
        patch("app.services.groq_whisper.subprocess.run") as convert,
    ):
        result = GroqWhisperTranscriber("test").transcribe(audio, "es")
    assert result.text == "Hola"
    assert b"synthetic audio" in b"".join(upload.call_args.args[0].data)
    convert.assert_not_called()


def test_next_chunk_is_prepared_during_upload_with_bounded_resources(tmp_path):
    from threading import Event, Lock

    from app.workers.job_worker import TranscriptionResult

    audio = tmp_path / "large.wav"
    with audio.open("wb") as source:
        source.truncate(25_000_001)
    second_ready = Event()
    uploading = Event()
    lock = Lock()
    active_encoders = 0
    maximum_encoders = 0
    maximum_files = 0
    uploads = []

    def convert(source, target, offset, length):
        nonlocal active_encoders, maximum_encoders, maximum_files
        with lock:
            active_encoders += 1
            maximum_encoders = max(maximum_encoders, active_encoders)
        if offset > 0:
            assert uploading.wait(timeout=2)
        target.write_bytes(b"prepared")
        with lock:
            maximum_files = max(maximum_files, len(list(target.parent.glob("*.flac"))))
            active_encoders -= 1
        if offset == 59:
            second_ready.set()

    def upload(path, language):
        uploads.append(path)
        assert path.read_bytes() == b"prepared"
        if len(uploads) == 1:
            uploading.set()
            assert second_ready.wait(timeout=2)
        return TranscriptionResult(language="es", duration_seconds=60,
                                   text="Audio", segments=[])

    transcriber = GroqWhisperTranscriber("test", chunk_seconds=60)
    with (
        patch.object(transcriber, "_get_duration", return_value=125),
        patch.object(transcriber, "_convert_chunk", side_effect=convert),
        patch.object(transcriber, "_transcribe_file", side_effect=upload),
    ):
        result = transcriber.transcribe(audio, "es")
    assert result.text == "Audio Audio Audio"
    assert len(uploads) == 3
    assert maximum_encoders == 1
    assert maximum_files == 2
    assert all(not path.exists() for path in uploads)


def test_upload_failure_waits_for_encoder_and_removes_all_chunks(tmp_path):
    from threading import Event

    audio = tmp_path / "large.wav"
    with audio.open("wb") as source:
        source.truncate(25_000_001)
    next_started = Event()
    stop_encoding = Event()
    paths = []

    def convert(source, target, offset, length):
        paths.append(target)
        if offset > 0:
            next_started.set()
            assert stop_encoding.wait(timeout=2)
        target.write_bytes(b"audio")

    def upload(*args):
        assert next_started.wait(timeout=2)
        stop_encoding.set()
        raise GroqAPIError("upload failed")

    transcriber = GroqWhisperTranscriber("test", chunk_seconds=60)
    with (
        patch.object(transcriber, "_get_duration", return_value=125),
        patch.object(transcriber, "_convert_chunk", side_effect=convert),
        patch.object(transcriber, "_transcribe_file", side_effect=upload),
        pytest.raises(GroqAPIError, match="upload failed"),
    ):
        transcriber.transcribe(audio, "es")
    assert len(paths) == 2
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("duration", ["nan", "inf", "0", "N/A"])
def test_invalid_audio_duration_is_rejected_safely(tmp_path, duration):
    from types import SimpleNamespace

    with patch("app.services.groq_whisper.subprocess.run",
               return_value=SimpleNamespace(stdout=duration)):
        with pytest.raises(GroqAPIError, match="No se puede leer el audio"):
            GroqWhisperTranscriber._get_duration(tmp_path / "audio.wav")


def test_conversion_failure_removes_partial_audio(tmp_path):
    import subprocess

    audio = tmp_path / "audio.aac"
    audio.write_bytes(b"video")
    converted_paths = []

    def convert(source, target, offset, length):
        target.write_bytes(b"partial audio")
        converted_paths.append(target)
        raise subprocess.TimeoutExpired("ffmpeg", 180)

    transcriber = GroqWhisperTranscriber("test-key")
    with (
        patch.object(transcriber, "_get_duration", return_value=60),
        patch.object(transcriber, "_convert_chunk", side_effect=convert),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        transcriber.transcribe(audio, "es")
    assert all(not path.exists() for path in converted_paths)
    assert audio.exists()
