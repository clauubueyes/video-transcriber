import socket

import pytest

from app.services.network_validation import (
    SourceHostResolutionError,
    UnsafeSourceHostError,
    validate_public_host,
)


def test_validator_accepts_global_ipv4_and_ipv6_addresses() -> None:
    addresses = validate_public_host(
        "www.youtube.com",
        resolver=lambda host: {"8.8.8.8", "2606:4700:4700::1111"},
    )

    assert {str(address) for address in addresses} == {
        "8.8.8.8",
        "2606:4700:4700::1111",
    }


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "::1", "fe80::1"])
def test_validator_rejects_non_public_addresses(address: str) -> None:
    with pytest.raises(UnsafeSourceHostError, match="pública"):
        validate_public_host("www.youtube.com", resolver=lambda host: {address})


def test_validator_rejects_unresolvable_hosts() -> None:
    def resolver(host: str) -> set[str]:
        raise socket.gaierror("unavailable")

    with pytest.raises(SourceHostResolutionError, match="validar"):
        validate_public_host("www.youtube.com", resolver=resolver)
