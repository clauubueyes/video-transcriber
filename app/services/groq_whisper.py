"""Adaptador de transcripción mediante la API gratuita de Groq (whisper-large-v3-turbo).

Inferencia ultrarrápida en la nube con cero coste de servidor local (0 MB RAM de modelo local).
"""

import json
import logging
from pathlib import Path
import urllib.request
import urllib.error
import uuid

from app.models.transcriptions import Segment
from app.workers.job_worker import TranscriptionResult

logger = logging.getLogger("video_transcriber.groq")


class GroqAPIError(RuntimeError):
    """Error al comunicarse con la API de Groq."""


class GroqWhisperTranscriber:
    """Transcribe audio enviándolo a la API ultrarrápida de Groq."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        endpoint: str = "https://api.groq.com/openai/v1/audio/transcriptions",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint

    def transcribe(
        self,
        audio_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        """Envía el archivo de audio local a Groq y devuelve el resultado normalizado."""
        if not audio_path.exists():
            raise FileNotFoundError(f"No existe el archivo de audio: {audio_path}")

        file_bytes = audio_path.read_bytes()

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body_parts = []

        def add_field(name: str, value: str) -> None:
            body_parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode("utf-8")
            )

        add_field("model", self._model)
        add_field("response_format", "verbose_json")
        if requested_language:
            add_field("language", requested_language)

        filename = audio_path.name
        content_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"

        file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")

        body = b"".join(body_parts) + file_header + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "video-transcriber/0.1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result_json = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error("groq_http_error status=%s", e.code)
            messages = {
                401: "Groq rechaza la clave de API. Revisa VIDEO_TRANSCRIBER_GROQ_API_KEY en .env y reinicia el servicio.",
                403: "Groq ha denegado el acceso a la transcripción.",
                413: "El archivo supera el tamaño admitido por Groq.",
                429: "Groq ha alcanzado su límite de uso. Inténtalo más tarde.",
            }
            raise GroqAPIError(messages.get(e.code, "Groq no ha podido procesar la transcripción.")) from e
        except Exception as e:
            logger.error("Fallo de conexión con Groq API: %s", e)
            raise GroqAPIError(f"Fallo de conexión con Groq API: {e}") from e

        raw_segments = result_json.get("segments", [])
        segments = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if text:
                segments.append(
                    Segment(
                        start=float(seg.get("start", 0.0)),
                        end=float(seg.get("end", 0.0)),
                        text=text,
                    )
                )

        full_text = result_json.get("text", "").strip()
        if not full_text and segments:
            full_text = " ".join(s.text for s in segments)

        detected_language = result_json.get("language") or requested_language
        duration = float(result_json.get("duration") or (segments[-1].end if segments else 0.0))

        return TranscriptionResult(
            language=detected_language,
            duration_seconds=duration,
            text=full_text,
            segments=segments,
        )
