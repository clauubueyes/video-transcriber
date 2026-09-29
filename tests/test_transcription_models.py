from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.transcriptions import (
    CreateTranscriptionRequest,
    JobStatus,
    Segment,
    TranscriptionJobResponse,
)


def test_request_requires_https_source() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        CreateTranscriptionRequest.model_validate(
            {"source": {"type": "url", "url": "http://youtube.com/watch?v=abc"}}
        )


def test_segment_ends_after_its_start() -> None:
    with pytest.raises(ValidationError, match="posterior"):
        Segment(start=5, end=5, text="Hola")


def test_response_serializes_documented_field_names() -> None:
    response = TranscriptionJobResponse(
        id="trn_abc123",
        status=JobStatus.QUEUED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert response.model_dump(by_alias=True)["createdAt"] == datetime(
        2026, 1, 1, tzinfo=UTC
    )
