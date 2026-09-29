from app.services.vtt import parse_vtt


def test_parse_vtt_extracts_normalized_segments() -> None:
    parsed = parse_vtt(
        """WEBVTT

NOTE metadato que no forma parte de la transcripción

00:00:01.000 --> 00:00:03.500 align:start
<i>Hola</i> mundo

2
00:01:02.000 --> 00:01:04.000
Siguiente paso
"""
    )

    assert parsed.text == "Hola mundo Siguiente paso"
    assert parsed.duration_seconds == 64
    assert [segment.model_dump() for segment in parsed.segments] == [
        {"start": 1, "end": 3.5, "text": "Hola mundo"},
        {"start": 62, "end": 64, "text": "Siguiente paso"},
    ]


def test_parse_vtt_ignores_non_cue_blocks() -> None:
    parsed = parse_vtt("WEBVTT\n\nSTYLE\n::cue { color: lime; }\n")

    assert parsed.text == ""
    assert parsed.duration_seconds == 0
    assert parsed.segments == []
