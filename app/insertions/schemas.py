"""Pydantic schemas for QM-13 quiz insertions in a course version."""

from app.schemas_common import ApiModel


class InsertionCreateResponse(ApiModel):
    """Response returned after inserting a quiz (``201 Created``)."""

    id_insertion: int
    apres_page: int
    ordre: int


class InsertedQuizSummary(ApiModel):
    """Summary of an inserted quiz returned in the sorted insertions list."""

    id_quiz: int
    titre: str
    nb_questions: int


class InsertionItemResponse(ApiModel):
    """One element in ``GET /api/cours/{idCours}/versions/{idVersion}/insertions``."""

    id_insertion: int
    type_element: str
    id_quiz: int | None = None
    quiz: InsertedQuizSummary | None = None
    apres_page: int
    ordre: int
