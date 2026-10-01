"""Validación de destinos públicos antes de acceder a un proveedor de vídeo."""

import socket
from collections.abc import Callable
from ipaddress import IPv4Address, IPv6Address, ip_address


class UnsafeSourceHostError(ValueError):
    """El host resuelve a una dirección no apta para acceder desde el servicio."""


class SourceHostResolutionError(ValueError):
    """El servicio no puede verificar las direcciones del host solicitado."""


AddressResolver = Callable[[str], set[str]]


def validate_public_host(
    host: str,
    resolver: AddressResolver | None = None,
) -> frozenset[IPv4Address | IPv6Address]:
    """Resuelve un host y acepta únicamente direcciones globalmente enrutable."""
    resolve = resolver or _resolve_host
    try:
        addresses = resolve(host)
    except OSError as error:
        raise SourceHostResolutionError(
            "No se ha podido validar la dirección del proveedor de vídeo."
        ) from error

    if not addresses:
        raise SourceHostResolutionError(
            "No se ha podido validar la dirección del proveedor de vídeo."
        )

    parsed_addresses = frozenset(ip_address(address) for address in addresses)
    if any(not address.is_global for address in parsed_addresses):
        raise UnsafeSourceHostError(
            "El proveedor de vídeo no usa una dirección pública."
        )
    return parsed_addresses


def _resolve_host(host: str) -> set[str]:
    records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return {record[4][0] for record in records}
