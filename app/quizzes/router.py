"""HTTP routes for QM-12 quizzes."""

import json

from fastapi import APIRouter, Request, Response, status

from app.dependencies import DbDep, TeacherDep
from app.exceptions import ValidationFailedError
from app.quizzes.schemas import QuizDetailResponse, QuizSummaryResponse
from app.quizzes.service import QuizService
from app.schemas_common import ValidationDetail

router = APIRouter(prefix="/api", tags=["quizzes"])


@router.post(
    "/cours/{id_cours}/quiz",
    response_model=QuizDetailResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_quiz(
    id_cours: int,
    request: Request,
    response: Response,
    teacher: TeacherDep,
    db: DbDep,
) -> QuizDetailResponse:
    """Create a quiz, its questions, and its insertion in one atomic transaction."""
    service = QuizService(db)
    # Check course existence and ownership before parsing JSON so 403/404 take precedence.
    service_course_check = service
    service_course_check._require_owned_course(teacher, id_cours)  # pylint: disable=protected-access
    raw_bytes = await request.body()
    try:
        raw_body = json.loads(raw_bytes) if raw_bytes else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationFailedError(
            [ValidationDetail(champ="body", code="CHAMP_INVALIDE", message="Corps JSON invalide")]
        ) from exc
    created = service.create_quiz(teacher, id_cours, raw_body)
    response.headers["Location"] = f"/api/quiz/{created.id_quiz}"
    return created


@router.get(
    "/cours/{id_cours}/quiz",
    response_model=list[QuizSummaryResponse],
    response_model_by_alias=True,
)
def list_quizzes(
    id_cours: int,
    teacher: TeacherDep,
    db: DbDep,
) -> list[QuizSummaryResponse]:
    """List summary information for all quizzes in a course."""
    return QuizService(db).list_quizzes(teacher, id_cours)


@router.get(
    "/quiz/{id_quiz}",
    response_model=QuizDetailResponse,
    response_model_by_alias=True,
)
def get_quiz(
    id_quiz: int,
    teacher: TeacherDep,
    db: DbDep,
) -> QuizDetailResponse:
    """Read a full quiz including correct answers."""
    return QuizService(db).get_quiz(teacher, id_quiz)
