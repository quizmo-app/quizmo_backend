"""Unit tests for JWT creation and verification."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.jwt_handler import create_access_token, decode_access_token
from app.config import Settings
from app.exceptions import AuthenticationError


@pytest.fixture
def settings() -> Settings:
    """Settings with a deterministic test secret."""
    return Settings(secret_key="unit-test-secret-key-0123456789-abcdefghij")


def test_token_round_trip_returns_teacher_id(settings: Settings) -> None:
    token = create_access_token("prof_a", settings)
    assert decode_access_token(token, settings) == "prof_a"


def test_expired_token_is_rejected(settings: Settings) -> None:
    token = create_access_token("prof_a", settings, expires_delta=timedelta(seconds=-5))
    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings)


def test_token_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    other = Settings(secret_key="another-secret-key-0123456789-abcdefghijklm")
    token = create_access_token("prof_a", other)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings)


def test_tampered_token_is_rejected(settings: Settings) -> None:
    token = create_access_token("prof_a", settings)
    header, payload, signature = token.split(".")
    tampered = ".".join([header, payload, signature[:-3] + "abc"])
    with pytest.raises(AuthenticationError):
        decode_access_token(tampered, settings)


def test_token_without_subject_is_rejected(settings: Settings) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = jwt.encode({"exp": expires}, settings.secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings)


def test_unsigned_token_is_rejected(settings: Settings) -> None:
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = jwt.encode({"sub": "prof_a", "exp": expires}, key=None, algorithm="none")
    with pytest.raises(AuthenticationError):
        decode_access_token(token, settings)


def test_garbage_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-jwt", settings)
