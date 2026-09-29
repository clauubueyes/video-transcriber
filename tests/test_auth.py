import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import require_service_token
from app.core.config import Settings


def settings() -> Settings:
    return Settings(token="test-token")


def test_valid_bearer_token_is_accepted() -> None:
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="test-token"
    )

    assert require_service_token(credentials, settings()) is None


@pytest.mark.parametrize(
    "credentials",
    [
        None,
        HTTPAuthorizationCredentials(scheme="Basic", credentials="test-token"),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token"),
    ],
)
def test_invalid_credentials_are_rejected(
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    with pytest.raises(HTTPException) as error:
        require_service_token(credentials, settings())

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}
