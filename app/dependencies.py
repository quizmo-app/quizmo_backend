"""FastAPI dependencies shared across routers."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app.auth.jwt_handler import decode_access_token
from app.config import Settings
from app.courses.pdf_storage import PdfStorage
from app.database import connect
from app.exceptions import AuthenticationError, DatabaseUnavailableError, SessionExpiredError

COOKIE_NAMES = ("access_token", "session")


def get_settings(request: Request) -> Settings:
    """Retrieve runtime settings stored on the FastAPI app state."""
    settings: Settings = request.app.state.settings
    return settings


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    """Open a per-request SQLite connection and close it on exit."""
    connection = connect(settings.database_path)
    try:
        yield connection
    finally:
        connection.close()


def get_insertions_db(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection for QM-13, translating sqlite errors into 503."""
    try:
        connection = connect(settings.database_path)
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError() from exc
    try:
        yield connection
    finally:
        connection.close()


def get_pdf_storage(settings: Annotated[Settings, Depends(get_settings)]) -> PdfStorage:
    """Provide the PDF storage service configured for this app."""
    return PdfStorage(settings.storage_dir)


def _extract_token(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credentials.strip():
            raise AuthenticationError()
        return credentials.strip()
    for name in COOKIE_NAMES:
        cookie_token = request.cookies.get(name)
        if cookie_token:
            return cookie_token
    raise AuthenticationError()


def _dev_teacher(request: Request, settings: Settings) -> str | None:
    """Teacher assumed for an anonymous request when ``QUIZMO_UTILISATEUR_DEV`` is set."""
    has_credentials = "authorization" in request.headers or any(
        request.cookies.get(name) for name in COOKIE_NAMES
    )
    return None if has_credentials else settings.utilisateur_dev


def get_current_teacher(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Authenticate the teacher via Bearer header or httpOnly cookie."""
    dev_teacher = _dev_teacher(request, settings)
    if dev_teacher:
        return dev_teacher
    token = _extract_token(request)
    return decode_access_token(token, settings)


def get_current_teacher_qm13(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Authenticate the teacher for QM-13, raising ``SessionExpiredError`` on failure."""
    dev_teacher = _dev_teacher(request, settings)
    if dev_teacher:
        return dev_teacher
    try:
        token = _extract_token(request)
        return decode_access_token(token, settings)
    except AuthenticationError as exc:
        raise SessionExpiredError() from exc


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
InsertionsDbDep = Annotated[sqlite3.Connection, Depends(get_insertions_db)]
PdfStorageDep = Annotated[PdfStorage, Depends(get_pdf_storage)]
TeacherDep = Annotated[str, Depends(get_current_teacher)]
InsertionsTeacherDep = Annotated[str, Depends(get_current_teacher_qm13)]
