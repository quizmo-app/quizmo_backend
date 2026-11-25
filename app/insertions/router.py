"""HTTP routes for QM-13 quiz insertions."""

import json

from fastapi import APIRouter, Request, status

from app.dependencies import InsertionsDbDep, InsertionsTeacherDep
from app.exceptions import InvalidPageError
from app.insertions.schemas import InsertionCreateResponse, InsertionItemResponse
from app.insertions.service import InsertionService

router = APIRouter(prefix="/api/cours", tags=["insertions"])


@router.post(
    "/{id_cours}/versions/{id_version}/insertions",
    response_model=InsertionCreateResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def insert_quiz_in_version(
    id_cours: int,
    id_version: int,
    request: Request,
    teacher: InsertionsTeacherDep,
    db: InsertionsDbDep,
) -> InsertionCreateResponse:
    """Insert an existing quiz after a given page of the active course version."""
    raw_bytes = await request.body()
    try:
        raw_body = json.loads(raw_bytes) if raw_bytes else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidPageError("Corps JSON invalide") from exc
    return InsertionService(db).insert_quiz(teacher, id_cours, id_version, raw_body)


@router.get(
    "/{id_cours}/versions/{id_version}/insertions",
    response_model=list[InsertionItemResponse],
    response_model_by_alias=True,
)
def list_version_insertions(
    id_cours: int,
    id_version: int,
    teacher: InsertionsTeacherDep,
    db: InsertionsDbDep,
) -> list[InsertionItemResponse]:
    """List insertions of a course version sorted by ``apresPage`` then ``ordre``."""
    return InsertionService(db).list_insertions(teacher, id_cours, id_version)
