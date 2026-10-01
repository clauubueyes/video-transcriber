"""Composición del procesamiento local, sin proveedores de IA externos."""

from pathlib import Path

from app.services.audio import YtDlpAudioFetcher
from app.services.audio_processor import AudioWhisperProcessor
from app.services.file_processor import LocalFileProcessor
from app.services.subtitle_processor import SubtitleFirstProcessor
from app.services.subtitles import YtDlpSubtitleFetcher
from app.services.whisper import FasterWhisperTranscriber
from app.workers.job_worker import TranscriptionProcessor


def create_local_processor(
    model_path: Path,
    *,
    device: str,
    compute_type: str,
) -> TranscriptionProcessor:
    """Crea el flujo VTT → audio → Whisper usando recursos de la máquina local."""
    audio_processor = AudioWhisperProcessor(
        YtDlpAudioFetcher(),
        FasterWhisperTranscriber(
            model_path,
            device=device,
            compute_type=compute_type,
        ),
    )
    return SubtitleFirstProcessor(YtDlpSubtitleFetcher(), audio_processor)


def create_local_file_processor(
    model_path: Path,
    *,
    device: str,
    compute_type: str,
) -> LocalFileProcessor:
    """Crea el procesamiento directo de ficheros con Whisper local."""
    return LocalFileProcessor(
        FasterWhisperTranscriber(
            model_path,
            device=device,
            compute_type=compute_type,
        )
    )
