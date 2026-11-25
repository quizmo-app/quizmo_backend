"""Integration tests for authentication transport (Bearer header and httpOnly cookie)."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

UNAUTHENTICATED = {"erreur": "NON_AUTHENTIFIE", "message": "Session absente ou expirée"}


def test_me_with_bearer_token(client: TestClient, headers_a: dict[str, str]) -> None:
    response = client.get("/api/auth/me", headers=headers_a)
    assert response.status_code == 200
    assert response.json() == {"idEnseignant": "prof_a"}


@pytest.mark.parametrize("cookie_name", ["access_token", "session"])
def test_me_with_httponly_cookie(
    client: TestClient, token_factory: Callable[..., str], cookie_name: str
) -> None:
    response = client.get("/api/auth/me", headers={"Cookie": f"{cookie_name}={token_factory()}"})
    assert response.status_code == 200
    assert response.json() == {"idEnseignant": "prof_a"}


def test_bearer_header_takes_precedence_over_cookie(
    client: TestClient, headers_a: dict[str, str], token_factory: Callable[..., str]
) -> None:
    headers = {**headers_a, "Cookie": f"access_token={token_factory('prof_b')}"}
    assert client.get("/api/auth/me", headers=headers).json() == {"idEnseignant": "prof_a"}


def test_invalid_bearer_is_not_rescued_by_a_valid_cookie(
    client: TestClient, token_factory: Callable[..., str]
) -> None:
    headers = {"Authorization": "Bearer garbage", "Cookie": f"access_token={token_factory()}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_missing_credentials_are_refused(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_expired_token_is_refused(client: TestClient, token_factory: Callable[..., str]) -> None:
    token = token_factory(expires_delta=timedelta(seconds=-10))
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_non_bearer_scheme_is_refused(client: TestClient) -> None:
    response = client.get("/api/auth/me", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


def test_logout_clears_the_cookie(client: TestClient, headers_a: dict[str, str]) -> None:
    response = client.post("/api/auth/logout", headers=headers_a)
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "access_token=" in cookie
    assert "Max-Age=0" in cookie


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["erreur"] == "HTTP_404"


def test_unexpected_error_returns_a_generic_envelope(settings: Settings) -> None:
    application = create_app(settings)

    @application.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "erreur": "ERREUR_INTERNE",
        "message": "Une erreur interne est survenue",
    }
