"""Conversión de subtítulos WebVTT a segmentos normalizados."""

import re
from dataclasses import dataclass
from pathlib import Path

from app.models.transcriptions import Segment

_TIMING_LINE = re.compile(
    r"^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})"
)
_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ParsedSubtitles:
    text: str
    duration_seconds: float
    segments: list[Segment]


def parse_vtt_file(path: Path) -> ParsedSubtitles:
    """Lee un archivo VTT UTF-8 y devuelve texto y marcas de tiempo."""
    return parse_vtt(path.read_text(encoding="utf-8"))


def parse_vtt(content: str) -> ParsedSubtitles:
    """Convierte las pistas de diálogo VTT, ignorando cabeceras y notas."""
    segments: list[Segment] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0] == "WEBVTT" or lines[0].startswith("NOTE"):
            continue

        timing_index = next(
            (index for index, line in enumerate(lines) if " --> " in line),
            None,
        )
        if timing_index is None:
            continue
        timing = _TIMING_LINE.match(lines[timing_index])
        if timing is None:
            continue

        text = " ".join(lines[timing_index + 1 :])
        text = _TAGS.sub("", text).strip()
        if not text:
            continue
        segments.append(
            Segment(
                start=_timestamp_to_seconds(timing.group("start")),
                end=_timestamp_to_seconds(timing.group("end")),
                text=text,
            )
        )

    return ParsedSubtitles(
        text=" ".join(segment.text for segment in segments),
        duration_seconds=max((segment.end for segment in segments), default=0),
        segments=segments,
    )


def _timestamp_to_seconds(timestamp: str) -> float:
    parts = timestamp.split(":")
    seconds = float(parts.pop())
    minutes = int(parts.pop())
    hours = int(parts.pop()) if parts else 0
    return hours * 3600 + minutes * 60 + seconds
