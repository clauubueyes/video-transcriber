"""Conversión de subtítulos WebVTT a segmentos normalizados."""

import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

from app.models.transcriptions import Segment

_TIMING_LINE = re.compile(
    r"^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})"
)
_TAGS = re.compile(r"<[^>]+>")
_MOJIBAKE_MARKERS = ("Ã", "Â", "â")
_MINIMUM_OVERLAP = 12


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

        text = _normalize_subtitle_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        start = _timestamp_to_seconds(timing.group("start"))
        end = _timestamp_to_seconds(timing.group("end"))
        if segments:
            text = _remove_previous_overlap(text, segments[-1].text)
            if not text:
                continue
            start = _start_after_previous_segment(start, end, segments[-1])
        segments.append(
            Segment(
                start=start,
                end=end,
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


def _normalize_subtitle_text(text: str) -> str:
    text = unescape(_TAGS.sub("", text)).strip()
    for _ in range(2):
        if not any(marker in text for marker in _MOJIBAKE_MARKERS):
            break
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired
    return " ".join(text.split())


def _remove_previous_overlap(text: str, previous_text: str) -> str:
    if text == previous_text:
        return ""
    if text.startswith(previous_text):
        return text[len(previous_text) :].strip()

    maximum = min(len(text), len(previous_text))
    for length in range(maximum, _MINIMUM_OVERLAP - 1, -1):
        if previous_text.endswith(text[:length]):
            return text[length:].strip()
    return text


def _start_after_previous_segment(start: float, end: float, previous: Segment) -> float:
    adjusted_start = max(start, previous.end)
    return adjusted_start if adjusted_start < end else start
