"""HTTP routes for QM-14 presentations and protected PDF page access."""

from fastapi import APIRouter, Response

from app.dependencies import DbDep, PdfStorageDep, TeacherDep
from app.presentations.schemas import PlanPresentationResponse, PositionJumpRequest
from app.presentations.service import PresentationService

router = APIRouter(tags=["presentations"])


@router.get(
    "/{course_id}/presentation",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def get_presentation(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Start or resume a course presentation and return its ordered plan."""
    return PresentationService(db, storage).start_or_resume(teacher, course_id)


@router.post(
    "/{course_id}/presentation/suivant",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def next_element(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Advance to the next element in the presentation plan."""
    return PresentationService(db, storage).step(teacher, course_id, delta=1)


@router.post(
    "/{course_id}/presentation/precedent",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def previous_element(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Go back to the previous element in the presentation plan."""
    return PresentationService(db, storage).step(teacher, course_id, delta=-1)


@router.put(
    "/{course_id}/presentation/position",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def jump_to_position(
    course_id: int,
    payload: PositionJumpRequest,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Jump directly to a plan position or PDF page number."""
    return PresentationService(db, storage).jump_to_position(teacher, course_id, payload)


@router.post(
    "/{course_id}/presentation/quiz/lancer",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def launch_quiz(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Launch the quiz at the current presentation position."""
    return PresentationService(db, storage).launch_quiz(teacher, course_id)


@router.post(
    "/{course_id}/presentation/quiz/cloturer",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def close_quiz(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Close the running quiz and return to the presentation."""
    return PresentationService(db, storage).close_quiz(teacher, course_id)


@router.post(
    "/{course_id}/presentation/interruption",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def interrupt_presentation(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Mark the active presentation as interrupted."""
    return PresentationService(db, storage).interrupt(teacher, course_id)


@router.post(
    "/{course_id}/presentation/terminer",
    response_model=PlanPresentationResponse,
    response_model_by_alias=True,
)
def terminate_presentation(
    course_id: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> PlanPresentationResponse:
    """Terminate the presentation and unlock the course."""
    return PresentationService(db, storage).terminate(teacher, course_id)


@router.get("/{course_id}/versions/{version_number}/pages/{page_number}")
def read_version_page(
    course_id: int,
    version_number: int,
    page_number: int,
    teacher: TeacherDep,
    db: DbDep,
    storage: PdfStorageDep,
) -> Response:
    """Serve a single PDF page after verifying course ownership."""
    content = PresentationService(db, storage).get_page_bytes(
        teacher, course_id, version_number, page_number
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Cache-Control": "private, max-age=3600"},
    )
