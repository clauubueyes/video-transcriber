from dataclasses import dataclass
from urllib.request import Request

import pytest

from app.services.redirect_validation import (
    UnsafeRedirectError,
    validate_redirect_chain,
)


@dataclass
class FakeResponse:
    status: int
    headers: dict[str, str]


def test_validator_follows_and_validates_each_redirect() -> None:
    responses = iter(
        [
            FakeResponse(302, {"Location": "https://www.youtube.com/watch?v=abc"}),
            FakeResponse(200, {}),
        ]
    )
    checked_hosts: list[str] = []

    def opener(request: Request) -> FakeResponse:
        return next(responses)

    result = validate_redirect_chain(
        "https://youtu.be/abc",
        host_validator=checked_hosts.append,
        opener=opener,
    )

    assert result == "https://www.youtube.com/watch?v=abc"
    assert checked_hosts == ["youtu.be", "www.youtube.com"]


def test_validator_rejects_insecure_redirect() -> None:
    def opener(request: Request) -> FakeResponse:
        return FakeResponse(302, {"Location": "http://127.0.0.1/private"})

    with pytest.raises(UnsafeRedirectError, match="segura"):
        validate_redirect_chain(
            "https://youtu.be/abc",
            host_validator=lambda host: object(),
            opener=opener,
        )


def test_validator_rejects_redirect_loop() -> None:
    def opener(request: Request) -> FakeResponse:
        return FakeResponse(302, {"Location": "https://youtu.be/abc"})

    with pytest.raises(UnsafeRedirectError, match="demasiadas"):
        validate_redirect_chain(
            "https://youtu.be/abc",
            host_validator=lambda host: object(),
            opener=opener,
            max_redirects=1,
        )
