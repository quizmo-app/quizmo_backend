"""Unit tests for the application settings."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_secret_is_random_and_long_enough() -> None:
    first, second = Settings(), Settings()
    assert len(first.secret_key) >= 32
    assert first.secret_key != second.secret_key


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(secret_key="too-short")


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.jwt_algorithm = "none"  # type: ignore[misc]


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("QUIZMO_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("QUIZMO_DATABASE_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("QUIZMO_STORAGE_DIR", str(tmp_path / "files"))
    settings = Settings.from_env()
    assert settings.secret_key == "k" * 40
    assert settings.database_path == tmp_path / "x.db"
    assert settings.storage_dir == tmp_path / "files"


def test_from_env_ignores_missing_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("QUIZMO_SECRET_KEY", "QUIZMO_DATABASE_PATH", "QUIZMO_STORAGE_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert len(Settings.from_env().secret_key) >= 32
