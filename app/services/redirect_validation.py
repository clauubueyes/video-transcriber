"""Prevalidación de redirecciones HTTP de una URL de vídeo."""

from collections.abc import Callable
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RedirectResponse(Protocol):
    status: int
    headers: object


RedirectOpener = Callable[[Request], RedirectResponse]
HostValidator = Callable[[str], object]


class UnsafeRedirectError(ValueError):
    """Una redirección no cumple las restricciones de origen seguro."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def validate_redirect_chain(
    source_url: str,
    host_validator: HostValidator,
    opener: RedirectOpener | None = None,
    max_redirects: int = 5,
) -> str:
    """Sigue redirecciones HTTP y valida HTTPS y host público en cada salto."""
    open_request = opener or _open_without_redirects
    current_url = source_url
    for _ in range(max_redirects + 1):
        parsed = urlparse(current_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UnsafeRedirectError("La redirección del vídeo no es segura.")
        host_validator(parsed.hostname)

        response = _request_without_following_redirects(current_url, open_request)
        location = getattr(response.headers, "get", lambda key: None)("Location")
        if response.status not in {301, 302, 303, 307, 308}:
            return current_url
        if not location:
            raise UnsafeRedirectError("La redirección del vídeo no es válida.")
        current_url = urljoin(current_url, location)

    raise UnsafeRedirectError("El vídeo contiene demasiadas redirecciones.")


def _request_without_following_redirects(
    url: str,
    opener: RedirectOpener,
) -> RedirectResponse:
    request = Request(url, method="HEAD")
    try:
        return opener(request)
    except HTTPError as error:
        return error


def _open_without_redirects(request: Request) -> RedirectResponse:
    return build_opener(_NoRedirectHandler()).open(request, timeout=10)
