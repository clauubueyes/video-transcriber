"""Composición de procesadores que comparten una instancia de transcripción."""

from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.services.audio import YtDlpAudioFetcher
from app.services.audio_processor import AudioTranscriber, AudioWhisperProcessor
from app.services.file_processor import LocalFileProcessor
from app.services.groq_whisper import GroqWhisperTranscriber
from app.services.subtitle_processor import SubtitleFirstProcessor
from app.services.subtitles import YtDlpSubtitleFetcher
from app.services.whisper import FasterWhisperTranscriber
from app.services.ytdlp import youtube_download_options
from app.workers.job_worker import TranscriptionProcessor


def create_local_processor(
    model_path: Path,
    *,
    device: str,
    compute_type: str,
    cookie_file: Path | None = None,
    download_options: dict[str, Any] | None = None,
    transcriber: AudioTranscriber | None = None,
) -> TranscriptionProcessor:
    """Crea el flujo VTT → audio → Whisper usando recursos de la máquina local."""
    audio_processor = AudioWhisperProcessor(
        YtDlpAudioFetcher(cookie_file=cookie_file, download_options=download_options),
        transcriber or FasterWhisperTranscriber(
            model_path,
            device=device,
            compute_type=compute_type,
        ),
    )
    return SubtitleFirstProcessor(
        YtDlpSubtitleFetcher(
            cookie_file=cookie_file, download_options=download_options,
        ),
        audio_processor,
    )


def create_local_file_processor(
    model_path: Path,
    *,
    device: str,
    compute_type: str,
    transcriber: AudioTranscriber | None = None,
) -> LocalFileProcessor:
    """Crea el procesamiento directo de ficheros con Whisper local."""
    return LocalFileProcessor(
        transcriber or FasterWhisperTranscriber(
            model_path,
            device=device,
            compute_type=compute_type,
        )
    )


def create_groq_processor(
    api_key: str,
    model: str = "whisper-large-v3-turbo",
    *,
    cookie_file: Path | None = None,
    download_options: dict[str, Any] | None = None,
    transcriber: AudioTranscriber | None = None,
) -> TranscriptionProcessor:
    """Crea el flujo VTT → audio → Groq API sin cargar un modelo local."""
    audio_processor = AudioWhisperProcessor(
        YtDlpAudioFetcher(cookie_file=cookie_file, download_options=download_options),
        transcriber or GroqWhisperTranscriber(api_key=api_key, model=model),
    )
    return SubtitleFirstProcessor(
        YtDlpSubtitleFetcher(
            cookie_file=cookie_file, download_options=download_options,
        ),
        audio_processor,
    )


def create_groq_file_processor(
    api_key: str,
    model: str = "whisper-large-v3-turbo",
    *,
    transcriber: AudioTranscriber | None = None,
) -> LocalFileProcessor:
    """Crea el procesamiento directo de ficheros usando Groq."""
    return LocalFileProcessor(
        transcriber or GroqWhisperTranscriber(api_key=api_key, model=model)
    )


def create_processors(
    settings: Settings,
) -> tuple[TranscriptionProcessor, LocalFileProcessor]:
    """Comparte modelo y ajustes entre URLs y archivos en API y worker."""
    options = youtube_download_options(settings)
    if settings.groq_api_key and settings.groq_api_key.get_secret_value():
        api_key = settings.groq_api_key.get_secret_value()
        transcriber = GroqWhisperTranscriber(
            api_key, settings.groq_model,
            chunk_seconds=settings.groq_chunk_seconds,
            timeout_seconds=settings.groq_timeout_seconds,
        )
        return (
            create_groq_processor(
                api_key, settings.groq_model,
                cookie_file=settings.youtube_cookie_file,
                download_options=options, transcriber=transcriber,
            ),
            create_groq_file_processor(
                api_key, settings.groq_model, transcriber=transcriber,
            ),
        )
    local_transcriber = FasterWhisperTranscriber(
        settings.model_path,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cpu_threads=settings.whisper_cpu_threads,
        beam_size=settings.whisper_beam_size,
    )
    return (
        create_local_processor(
            settings.model_path,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            cookie_file=settings.youtube_cookie_file,
            download_options=options, transcriber=local_transcriber,
        ),
        create_local_file_processor(
            settings.model_path,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            transcriber=local_transcriber,
        ),
    )
