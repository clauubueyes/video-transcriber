"""Transcripción con Groq y subidas de audio con memoria acotada."""

import json
import logging
import math
import mimetypes
import subprocess
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.transcriptions import Segment
from app.workers.job_worker import TranscriptionResult

logger = logging.getLogger("video_transcriber.groq")

_MAX_REQUEST_AUDIO_BYTES = 25_000_000
_PREPARE_ABOVE_BYTES = 20_000_000
_READ_BYTES = 64 * 1024


class StreamingMultipart:
    """Cuerpo HTTP iterable; solo mantiene un bloque de audio en memoria."""

    def __init__(self, prefix: bytes, audio_path: Path, suffix: bytes) -> None:
        self._prefix = prefix
        self._audio_path = audio_path
        self._suffix = suffix
        self.content_length = len(prefix) + audio_path.stat().st_size + len(suffix)

    def __iter__(self) -> Iterator[bytes]:
        yield self._prefix
        with self._audio_path.open("rb") as source:
            while block := source.read(_READ_BYTES):
                yield block
        yield self._suffix


class GroqAPIError(RuntimeError):
    """Error al comunicarse con la API de Groq."""


class GroqWhisperTranscriber:
    """Transcribe audio enviándolo a la API ultrarrápida de Groq."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        endpoint: str = "https://api.groq.com/openai/v1/audio/transcriptions",
        *,
        chunk_seconds: int = 600,
        timeout_seconds: int = 120,
    ) -> None:
        if not 30 <= chunk_seconds <= 600:
            raise ValueError("Los bloques deben durar entre 30 y 600 segundos.")
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._chunk_seconds = chunk_seconds
        self._timeout_seconds = timeout_seconds

    def transcribe(
        self,
        audio_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        """Envía audio a Groq y devuelve texto y marcas de tiempo."""
        if not audio_path.exists():
            raise FileNotFoundError(f"No existe el archivo de audio: {audio_path}")

        if (
            audio_path.stat().st_size >= _PREPARE_ABOVE_BYTES
            or audio_path.suffix.lower() in {".mp4", ".webm", ".aac", ".opus"}
        ):
            return self._transcribe_chunks(audio_path, requested_language)
        return self._transcribe_file(audio_path, requested_language)

    def _transcribe_chunks(
        self, audio_path: Path, requested_language: str | None,
    ) -> TranscriptionResult:
        """Extrae solo audio; genera, envía y borra un bloque cada vez."""
        duration = self._get_duration(audio_path)
        segments: list[Segment] = []
        texts: list[str] = []
        language = requested_language
        with TemporaryDirectory(prefix="groq-audio-") as directory:
            chunk = Path(directory) / "chunk.flac"
            for index in range(math.ceil(duration / self._chunk_seconds)):
                start = index * self._chunk_seconds
                end = min(start + self._chunk_seconds, duration)
                # Un segundo de contexto por lado; cada bloque conserva el centro.
                offset = max(0, start - 1)
                length = min(duration, end + 1) - offset
                self._convert_chunk(audio_path, chunk, offset, length)
                result = self._transcribe_file(chunk, requested_language)
                language = language or result.language
                kept_segments = []
                for segment in result.segments:
                    midpoint = offset + (segment.start + segment.end) / 2
                    if start <= midpoint < end:
                        kept_segments.append(Segment(
                            start=max(start, segment.start + offset),
                            end=min(end, segment.end + offset),
                            text=segment.text,
                        ))
                segments.extend(kept_segments)
                text = " ".join(segment.text for segment in kept_segments)
                if not result.segments:
                    text = result.text
                if text:
                    texts.append(text)
                chunk.unlink()
        return TranscriptionResult(
            language=language,
            duration_seconds=duration,
            text=" ".join(texts),
            segments=segments,
        )

    @staticmethod
    def _get_duration(audio_path: Path) -> float:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True, text=True, check=True, timeout=30,
            )
            duration = float(result.stdout.strip())
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Duración no válida.")
            return duration
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise GroqAPIError(
                "No se puede leer el audio. Comprueba el archivo y que FFmpeg "
                "y FFprobe estén instalados (Docker ya los incluye)."
            ) from error

    @staticmethod
    def _convert_chunk(
        source: Path, target: Path, offset: float, length: float,
    ) -> None:
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1",
                 "-ss", str(offset), "-i", str(source), "-t", str(length),
                 "-map", "0:a:0", "-vn", "-ar", "16000", "-ac", "1",
                 "-c:a", "flac", "-sample_fmt", "s16", "-threads", "1",
                 str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, timeout=180,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GroqAPIError(
                "No se ha podido preparar el audio con FFmpeg."
            ) from error

    def _transcribe_file(
        self, audio_path: Path, requested_language: str | None,
    ) -> TranscriptionResult:
        if audio_path.stat().st_size > _MAX_REQUEST_AUDIO_BYTES:
            raise GroqAPIError("El bloque de audio supera el tamaño admitido por Groq.")

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

        filename = "audio" + audio_path.suffix.lower()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")

        body = StreamingMultipart(
            b"".join(body_parts) + file_header,
            audio_path,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        )

        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(body.content_length),
                "User-Agent": "video-transcriber/0.1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                result_json = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error("groq_http_error status=%s", e.code)
            messages = {
                401: "Groq rechaza la clave de API. Revisa "
                     "VIDEO_TRANSCRIBER_GROQ_API_KEY en .env y reinicia el servicio.",
                403: "Groq ha denegado el acceso a la transcripción.",
                413: "El archivo supera el tamaño admitido por Groq.",
                429: "Groq ha alcanzado su límite de uso. Inténtalo más tarde.",
            }
            raise GroqAPIError(messages.get(
                e.code, "Groq no ha podido procesar la transcripción.",
            )) from e
        except Exception as e:
            logger.error("groq_connection_failed type=%s", type(e).__name__)
            raise GroqAPIError("No se ha podido conectar con Groq.") from e

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
        duration = float(
            result_json.get("duration") or (segments[-1].end if segments else 0.0)
        )

        return TranscriptionResult(
            language=detected_language,
            duration_seconds=duration,
            text=full_text,
            segments=segments,
        )
