"""Pruebas repetibles con audio real, sin guardar el texto transcrito."""

import argparse
import json
import math
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from threading import Event, Thread
from time import perf_counter

from app.core.config import Settings
from app.services.audio_processor import AudioTranscriber
from app.services.groq_whisper import GroqWhisperTranscriber
from app.services.whisper import FasterWhisperTranscriber


class MemorySampler:
    """Muestrea la suma de RSS del proceso y sus descendientes cada 50 ms."""

    def __init__(self) -> None:
        try:
            import psutil
        except ImportError:
            self._psutil = None
        else:
            self._psutil = psutil
        self.peak_rss_bytes: int | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def _sample(self) -> None:
        if self._psutil is None:
            return
        try:
            process = self._psutil.Process()
            rss = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except self._psutil.Error:
                    # Un proceso temporal puede terminar entre ambas lecturas.
                    continue
            self.peak_rss_bytes = max(self.peak_rss_bytes or 0, rss)
        except self._psutil.Error:
            return

    def _run(self) -> None:
        while not self._stop.wait(0.05):
            self._sample()

    def __enter__(self):
        self._sample()
        if self._psutil is not None:
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self._sample()


@dataclass(frozen=True)
class BenchmarkRun:
    run: int
    status: str
    processing_seconds: float
    audio_duration_seconds: float
    processing_speed: float | None
    peak_rss_bytes: int | None
    error_type: str | None = None


def get_media_duration(path: Path) -> float:
    """Obtiene la duración completa del archivo, incluidos los silencios."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        duration = float(result.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Duración no válida.")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ValueError(
            "No se puede medir el archivo. Comprueba que sea un audio o vídeo "
            "válido y que FFprobe esté instalado."
        ) from error
    return duration


def run_benchmark(
    transcriber: AudioTranscriber,
    path: Path,
    language: str | None,
    *,
    runs: int,
    audio_duration_seconds: float,
) -> list[BenchmarkRun]:
    """Reutiliza un transcriptor y registra también los intentos fallidos."""
    results = []
    for run in range(1, runs + 1):
        error_type = None
        with MemorySampler() as memory:
            started_at = perf_counter()
            try:
                # Consume los segmentos dentro del adaptador; no guarda texto.
                transcriber.transcribe(path, language)
            except Exception as error:
                error_type = type(error).__name__
            processing_seconds = perf_counter() - started_at
        successful = error_type is None
        results.append(BenchmarkRun(
            run=run,
            status="completed" if successful else "failed",
            processing_seconds=processing_seconds,
            audio_duration_seconds=audio_duration_seconds,
            processing_speed=audio_duration_seconds / processing_seconds
            if successful and processing_seconds > 0 else None,
            peak_rss_bytes=memory.peak_rss_bytes,
            error_type=error_type,
        ))
    return results


def summarize_runs(runs: list[BenchmarkRun]) -> dict[str, int | float | None]:
    completed = [run for run in runs if run.status == "completed"]
    times = [run.processing_seconds for run in completed]
    speeds = [run.processing_speed for run in completed
              if run.processing_speed is not None]
    memory = [run.peak_rss_bytes for run in completed
              if run.peak_rss_bytes is not None]
    return {
        "attempts": len(runs),
        "completed": len(completed),
        "failed": len(runs) - len(completed),
        "success_rate": len(completed) / len(runs) if runs else None,
        "median_processing_seconds": median(times) if times else None,
        "median_processing_speed": median(speeds) if speeds else None,
        "max_sampled_rss_bytes": max(memory) if memory else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de Video Transcriber")
    parser.add_argument("file", type=Path, help="Audio o vídeo local de prueba.")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--language", default="es")
    parser.add_argument(
        "--provider", choices=("local", "groq"), default="local",
        help="Local por defecto. Groq envía el archivo y consume cuota de su API.",
    )
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path("data/benchmarks/report.json"))
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.runs <= 100:
        parser.error("--runs debe estar entre 1 y 100.")
    if not arguments.file.is_file():
        parser.error("El archivo de prueba no existe.")
    if arguments.output.resolve() == arguments.file.resolve():
        parser.error("El informe debe guardarse en un archivo distinto al audio.")

    # La prueba no inicia una API y no necesita su token de servicio.
    settings = Settings(token="benchmark-unused")
    if arguments.model_path is not None:
        settings.model_path = arguments.model_path
    if arguments.provider == "local":
        if not settings.model_path.is_dir():
            parser.error("No hay modelo local. Configura --model-path o MODEL_PATH.")
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            parser.error("Instala las dependencias del proyecto para usar Whisper.")
        transcriber = FasterWhisperTranscriber(
            settings.model_path, device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            cpu_threads=settings.whisper_cpu_threads,
            beam_size=settings.whisper_beam_size,
        )
        model = settings.model_path.name
    else:
        if not settings.groq_api_key or not settings.groq_api_key.get_secret_value():
            parser.error("Configura VIDEO_TRANSCRIBER_GROQ_API_KEY en .env.")
        transcriber = GroqWhisperTranscriber(
            settings.groq_api_key.get_secret_value(), settings.groq_model,
            chunk_seconds=settings.groq_chunk_seconds,
            timeout_seconds=settings.groq_timeout_seconds,
        )
        model = settings.groq_model
    try:
        audio_duration = get_media_duration(arguments.file)
    except ValueError as error:
        parser.error(str(error))
    results = run_benchmark(
        transcriber, arguments.file, arguments.language,
        runs=arguments.runs, audio_duration_seconds=audio_duration,
    )
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider": arguments.provider,
        "model": model,
        "language": arguments.language,
        "file_bytes": arguments.file.stat().st_size,
        "audio_duration_seconds": audio_duration,
        "hardware": {
            "os": platform.system(), "architecture": platform.machine(),
            "processor": platform.processor(), "logical_cpus": os.cpu_count(),
        },
        "local_settings": {
            "device": settings.whisper_device,
            "compute_type": settings.whisper_compute_type,
            "cpu_threads": settings.whisper_cpu_threads,
            "beam_size": settings.whisper_beam_size,
        } if arguments.provider == "local" else None,
        "memory_sample_interval_seconds": 0.05,
        "runs": [asdict(result) for result in results],
        "summary": summarize_runs(results),
        "subsequent_runs_summary": summarize_runs(results[1:]),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Informe: {arguments.output}")
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
