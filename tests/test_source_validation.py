import pytest
from pydantic import AnyHttpUrl

from app.services.source_validation import (
    SourceNotAllowedError,
    validate_allowed_source,
)

ALLOWED_DOMAINS = frozenset({"youtube.com", "www.youtube.com", "youtu.be"})


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
    ],
)
def test_allows_configured_youtube_hosts(url: str) -> None:
    validate_allowed_source(AnyHttpUrl(url), ALLOWED_DOMAINS)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.example.test/watch?v=abc",
        "https://evil-youtube.com/watch?v=abc",
    ],
)
def test_rejects_hosts_that_only_resemble_allowed_domains(url: str) -> None:
    with pytest.raises(SourceNotAllowedError, match="no es compatible"):
        validate_allowed_source(AnyHttpUrl(url), ALLOWED_DOMAINS)
