"""JWT creation and verification."""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import Settings
from app.exceptions import AuthenticationError


def create_access_token(
    teacher_id: str, settings: Settings, expires_delta: timedelta | None = None
) -> str:
    """Sign a token whose subject is the teacher's LDAP identifier."""
    lifetime = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.token_expire_minutes)
    )
    claims = {"sub": teacher_id, "exp": datetime.now(timezone.utc) + lifetime}
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> str:
    """Return the teacher id carried by a valid token, otherwise raise ``AuthenticationError``."""
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError() from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError()
    return subject
