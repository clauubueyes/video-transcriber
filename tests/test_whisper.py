from dataclasses import dataclass

import pytest

from app.models.transcriptions import Segment
from app.services.whisper import FasterWhisperTranscriber, LocalModelNotFoundError


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str


@dataclass
class FakeInfo:
    language: str


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(
        self,
        audio: str,
        *,
        language: str | None,
        vad_filter: bool,
        beam_size: int,
    ) -> tuple[list[FakeSegment], FakeInfo]:
        self.calls += 1
        assert audio.endswith("video.m4a")
        assert language == "es"
        assert vad_filter is True
        assert beam_size == 5
        return [FakeSegment(0, 1.5, " Hola ")], FakeInfo("es")


def test_transcriber_uses_local_model_and_caches_it(tmp_path) -> None:
    model_path = tmp_path / "whisper-small"
    model_path.mkdir()
    audio_path = tmp_path / "video.m4a"
    audio_path.write_bytes(b"audio")
    model = FakeModel()
    factory_calls = 0

    def factory(path: str, device: str, compute_type: str) -> FakeModel:
        nonlocal factory_calls
        factory_calls += 1
        assert path == str(model_path)
        assert device == "cpu"
        assert compute_type == "int8"
        return model

    transcriber = FasterWhisperTranscriber(model_path, model_factory=factory)
    first = transcriber.transcribe(audio_path, "es")
    second = transcriber.transcribe(audio_path, "es")

    assert first.text == "Hola"
    assert first.segments == [Segment(start=0, end=1.5, text="Hola")]
    assert second.language == "es"
    assert factory_calls == 1
    assert model.calls == 2


def test_transcriber_requires_preinstalled_local_model(tmp_path) -> None:
    transcriber = FasterWhisperTranscriber(tmp_path / "missing")
    audio_path = tmp_path / "video.m4a"
    audio_path.write_bytes(b"audio")

    with pytest.raises(LocalModelNotFoundError, match="modelo local"):
        transcriber.transcribe(audio_path, "es")


def test_concurrent_first_use_loads_only_one_model(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from time import sleep

    model = FakeModel()
    loads = []
    barrier = Barrier(4)

    def factory(*args):
        loads.append(args)
        sleep(0.02)
        return model

    transcriber = FasterWhisperTranscriber(tmp_path, model_factory=factory)

    def load(_):
        barrier.wait(timeout=2)
        return transcriber._get_model()

    with ThreadPoolExecutor(max_workers=4) as executor:
        models = list(executor.map(load, range(4)))
    assert all(instance is model for instance in models)
    assert len(loads) == 1
