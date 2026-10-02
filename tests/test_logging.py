import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_emits_only_safe_operational_fields() -> None:
    record = logging.LogRecord(
        name="video_transcriber.worker",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="job_completed",
        args=(),
        exc_info=None,
    )
    record.job_id = "trn_abc"
    record.status = "completed"
    record.duration_seconds = 42
    record.removed_uploads = 3
    record.transcript_text = "contenido que no debe aparecer"
    record.token = "secreto que no debe aparecer"

    event = json.loads(JsonFormatter().format(record))

    assert event["job_id"] == "trn_abc"
    assert event["status"] == "completed"
    assert event["duration_seconds"] == 42
    assert event["removed_uploads"] == 3
    assert "transcript_text" not in event
    assert "token" not in event
