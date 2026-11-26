"""Base Pydantic models and helpers shared by every feature package."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

MSG_REQUIRED = "Ce champ est obligatoire"
MSG_INVALID = "Valeur invalide pour ce champ"
MSG_POSITION = "Position d'insertion invalide"
MSG_DURATION = "Durée hors des bornes autorisées"

# Discriminator values of tagged unions: pydantic adds them to error locations.
UNION_TAGS = frozenset({"QCM", "LIBRE", "RELIER"})


class SnakeModel(BaseModel):
    """Immutable model whose JSON keys are snake_case (QM-17 contract)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class ApiModel(BaseModel):
    """Immutable model whose JSON keys are camelCase (QM-12 and QM-14 contracts)."""

    model_config = ConfigDict(frozen=True, alias_generator=to_camel, populate_by_name=True)


class ValidationDetail(SnakeModel):
    """One problem reported in the ``details`` list of a 400 response."""

    champ: str
    code: str
    message: str


class InsertionInfo(ApiModel):
    """Where an item sits in a course version."""

    id_insertion: int
    id_version: int
    apres_page: int


def required_detail(champ: str) -> ValidationDetail:
    """Detail for a missing or blank mandatory field."""
    return ValidationDetail(champ=champ, code="CHAMP_OBLIGATOIRE", message=MSG_REQUIRED)


def position_detail(champ: str, message: str = MSG_POSITION) -> ValidationDetail:
    """Detail for an insertion position outside the course."""
    return ValidationDetail(champ=champ, code="POSITION_INVALIDE", message=message)


def duration_detail(champ: str) -> ValidationDetail:
    """Detail for a duration outside the allowed bounds."""
    return ValidationDetail(champ=champ, code="DUREE_INVALIDE", message=MSG_DURATION)


def is_valid_position(value: int | None, page_count: int) -> bool:
    """A position is valid when it is an existing page number."""
    return value is not None and 1 <= value <= page_count


def format_path(parts: Sequence[str | int]) -> str:
    """Render a location such as ``questions[0].configuration.options``."""
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


def detail_from_pydantic_error(error: Mapping[str, Any]) -> ValidationDetail:
    """Translate one pydantic/FastAPI validation error into a ``ValidationDetail``."""
    kind = str(error["type"])
    if kind == "json_invalid":
        return ValidationDetail(champ="body", code="CHAMP_INVALIDE", message="Corps JSON invalide")
    raw_loc = list(error["loc"])
    if raw_loc and raw_loc[0] == "body":
        raw_loc = raw_loc[1:]
    parts = [part for part in raw_loc if part not in UNION_TAGS]
    if kind in ("union_tag_invalid", "union_tag_not_found"):
        parts.append("type")
    champ = format_path(parts)
    if kind in ("missing", "union_tag_not_found"):
        return required_detail(champ)
    return ValidationDetail(champ=champ, code="CHAMP_INVALIDE", message=MSG_INVALID)
