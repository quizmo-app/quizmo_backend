"""Pydantic schemas for QM-14 course presentations."""

from typing import Literal

from app.schemas_common import ApiModel


class PlanElementResponse(ApiModel):
    """One element in the presentation plan (PDF page, quiz, or leaderboard)."""

    position: int
    type: Literal["PAGE", "QUIZ", "LEADERBOARD"]
    numero_page: int | None = None
    page_url: str | None = None
    preload_page_url: str | None = None
    id_quiz: int | None = None
    id_leaderboard: int | None = None
    titre: str | None = None
    apres_page: int | None = None


class PlanPresentationResponse(ApiModel):
    """Current state and ordered plan of a course presentation."""

    id_presentation: int
    id_cours: int
    titre: str
    version: int
    etat: str
    position_courante: int
    nb_elements: int
    element: PlanElementResponse
    elements: list[PlanElementResponse]


class PositionJumpRequest(ApiModel):
    """Direct navigation target (either plan ``position`` or PDF ``numeroPage``)."""

    position: int | None = None
    numero_page: int | None = None
