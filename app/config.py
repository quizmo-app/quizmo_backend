"""Application settings."""

import os
import secrets
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

_ENV_MAPPING = {
    "QUIZMO_SECRET_KEY": "secret_key",
    "QUIZMO_DATABASE_PATH": "database_path",
    "QUIZMO_STORAGE_DIR": "storage_dir",
}


class Settings(BaseModel):
    """Immutable runtime configuration (secrets come from the environment, never from code)."""

    model_config = ConfigDict(frozen=True)

    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=32)
    jwt_algorithm: str = "HS256"
    token_expire_minutes: int = Field(default=60, gt=0)
    database_path: Path = Path("data/quizmo.db")
    storage_dir: Path = Path("storage")
    allowed_origins: tuple[str, ...] = ("http://localhost:5173",)

    @classmethod
    def from_env(cls) -> Self:
        """Build the settings from ``QUIZMO_*`` environment variables."""
        values = {
            field: os.environ[variable]
            for variable, field in _ENV_MAPPING.items()
            if os.environ.get(variable)
        }
        return cls(**values)
