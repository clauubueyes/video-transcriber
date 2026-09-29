from pathlib import Path

from app.models.transcriptions import Segment
from app.services.audio_processor import AudioWhisperProcessor
from app.workers.job_worker import TranscriptionResult


class FakeAudioFetcher:
    def fetch(self, source_url: str, temporary_directory: Path) -> Path:
        assert source_url == "https://www.youtube.com/watch?v=abc"
        audio_path = temporary_directory / "video.m4a"
        audio_path.write_bytes(b"audio")
        return audio_path


class FakeTranscriber:
    def __init__(self) -> None:
        self.audio_path: Path | None = None

    def transcribe(
        self,
        audio_path: Path,
        requested_language: str | None,
    ) -> TranscriptionResult:
        self.audio_path = audio_path
        assert requested_language == "es"
        return TranscriptionResult(
            language="es",
            duration_seconds=2,
            text="Audio local",
            segments=[Segment(start=0, end=2, text="Audio local")],
        )


def test_processor_transcribes_downloaded_audio_in_temporary_directory() -> None:
    transcriber = FakeTranscriber()
    processor = AudioWhisperProcessor(FakeAudioFetcher(), transcriber)  # type: ignore[arg-type]

    result = processor.process("https://www.youtube.com/watch?v=abc", "es")

    assert result.text == "Audio local"
    assert transcriber.audio_path is not None
    assert not transcriber.audio_path.exists()
