"""Validación de orígenes antes de que un worker descargue contenido."""

from pydantic import AnyHttpUrl


class SourceNotAllowedError(ValueError):
    """La URL no pertenece a uno de los proveedores habilitados."""


def validate_allowed_source(
    url: AnyHttpUrl, allowed_domains: frozenset[str]
) -> None:
    """Comprueba coincidencia exacta del host contra la lista permitida.

    La coincidencia exacta evita aceptar dominios engañosos como
    ``youtube.com.example.test``. Las redirecciones se validarán de nuevo en el
    adaptador de descarga antes de acceder a su destino.
    """
    host = url.host.lower()
    if host not in allowed_domains:
        raise SourceNotAllowedError("Este proveedor de vídeo no es compatible.")
