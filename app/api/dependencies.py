"""Dependencias compartidas por las rutas protegidas."""

from functools import lru_cache
from secrets import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_settings() -> Settings:
    """Carga la configuración una vez por proceso."""
    return Settings()


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Rechaza solicitudes sin el token de servicio configurado."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales no válidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    if not compare_digest(credentials.credentials, settings.token.get_secret_value()):
        raise unauthorized
