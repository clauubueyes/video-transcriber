import json
from types import SimpleNamespace

import pytest

from app import benchmark
from app.benchmark import BenchmarkRun, MemorySampler
from app.workers.job_worker import TranscriptionResult


def test_benchmark_records_failures_and_summarizes_only_successful_runs(
    tmp_path, monkeypatch,
):
    times = iter([0, 2, 10, 11, 20, 24])
    monkeypatch.setattr(benchmark, "perf_counter", lambda: next(times))

    class Processor:
        calls = 0

        def transcribe(self, path, language):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("Private token and transcript must stay private")
            return TranscriptionResult("es", 1, "Private transcript", [])

    results = benchmark.run_benchmark(
        Processor(), tmp_path / "audio.wav", "es",
        runs=3, audio_duration_seconds=120,
    )
    summary = benchmark.summarize_runs(results)

    assert [run.status for run in results] == ["completed", "failed", "completed"]
    assert results[0].processing_speed == 60  # Uses full media duration, not text.
    assert results[1].processing_speed is None
    assert results[1].error_type == "RuntimeError"
    assert summary["median_processing_seconds"] == 3
    assert summary["success_rate"] == pytest.approx(2 / 3)
    assert "Private" not in repr(results)
    assert "Private" not in repr(summary)


def test_empty_or_failed_benchmark_has_no_speed_or_time_median():
    failed = BenchmarkRun(1, "failed", 1, 120, None, None, "RuntimeError")

    assert benchmark.summarize_runs([])["success_rate"] is None
    summary = benchmark.summarize_runs([failed])
    assert summary["success_rate"] == 0
    assert summary["median_processing_seconds"] is None
    assert summary["median_processing_speed"] is None


def test_memory_sampler_counts_descendants_and_handles_disappearing_processes():
    class ProcessError(Exception):
        pass

    class Child:
        def memory_info(self):
            return SimpleNamespace(rss=30)

    class DisappearingChild:
        def memory_info(self):
            raise ProcessError

    class Process:
        def memory_info(self):
            return SimpleNamespace(rss=100)

        def children(self, recursive):
            assert recursive
            return [Child(), DisappearingChild()]

    sampler = MemorySampler()
    sampler._psutil = SimpleNamespace(Process=Process, Error=ProcessError)
    sampler._sample()
    assert sampler.peak_rss_bytes == 130


def test_memory_sampling_is_optional():
    sampler = MemorySampler()
    sampler._psutil = None
    with sampler:
        pass
    assert sampler.peak_rss_bytes is None


@pytest.mark.parametrize("duration", ["nan", "inf", "0", "N/A"])
def test_benchmark_rejects_invalid_duration(monkeypatch, tmp_path, duration):
    monkeypatch.setattr(benchmark.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(stdout=duration))

    with pytest.raises(ValueError, match="FFprobe"):
        benchmark.get_media_duration(tmp_path / "audio.wav")


def test_cli_defaults_to_local_even_if_groq_is_configured(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(benchmark, "Settings", lambda **kw: SimpleNamespace(
        model_path=tmp_path / "missing-model", groq_api_key="private-api-key",
    ))
    monkeypatch.setattr(benchmark, "GroqWhisperTranscriber",
                        lambda *a, **kw: pytest.fail("Unexpected remote request"))

    with pytest.raises(SystemExit) as error:
        benchmark.main([str(audio)])
    assert error.value.code == 2


def test_cli_writes_report_without_content_paths_or_secrets(tmp_path, monkeypatch):
    from app.core.config import Settings

    audio = tmp_path / "private-file.wav"
    audio.write_bytes(b"private audio")
    output = tmp_path / "reports" / "benchmark.json"
    settings = Settings(_env_file=None, token="private-token",
                        groq_api_key="private-api-key")
    monkeypatch.setattr(benchmark, "Settings", lambda **kw: settings)
    monkeypatch.setattr(benchmark, "GroqWhisperTranscriber", lambda *a, **kw: object())
    monkeypatch.setattr(benchmark, "get_media_duration", lambda path: 120)
    runs = [BenchmarkRun(1, "completed", 4, 120, 30, 100),
            BenchmarkRun(2, "completed", 2, 120, 60, 100)]
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *a, **kw: runs)

    code = benchmark.main([str(audio), "--provider", "groq", "--runs", "2",
                           "--output", str(output)])
    raw = output.read_text(encoding="utf-8")
    report = json.loads(raw)

    assert code == 0
    assert report["summary"]["median_processing_seconds"] == 3
    assert report["subsequent_runs_summary"]["median_processing_seconds"] == 2
    assert report["provider"] == "groq"
    assert report["local_settings"] is None
    assert "private" not in raw


def test_cli_cannot_overwrite_input_file(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"keep this audio")

    with pytest.raises(SystemExit):
        benchmark.main([str(audio), "--output", str(audio)])
    assert audio.read_bytes() == b"keep this audio"
