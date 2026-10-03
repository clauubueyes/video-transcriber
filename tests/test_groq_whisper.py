"""Pruebas unitarias del adaptador de Groq Whisper API."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.groq_whisper import GroqAPIError, GroqWhisperTranscriber


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
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hola mundo"
    assert result.segments[1].end == 5.0


def test_groq_whisper_transcribe_file_not_found(tmp_path: Path):
    transcriber = GroqWhisperTranscriber(api_key="gsk_test_key")
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe(tmp_path / "nonexistent.mp3", requested_language=None)
