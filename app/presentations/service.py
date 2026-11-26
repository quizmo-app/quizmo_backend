"""Business logic for QM-14 course presentations and protected PDF page delivery."""

import sqlite3
from dataclasses import replace

from app.courses.pdf_storage import PdfStorage
from app.courses.records import CourseRecord, InsertionRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.database import transaction, utc_now
from app.exceptions import (
    AccessDeniedError,
    CourseArchivedError,
    CourseNotFoundError,
    InternalStorageError,
    PageNotFoundError,
    PdfUnavailableError,
    PresentationNotFoundError,
    PresentationStateError,
    ValidationFailedError,
    VersionNotFoundError,
)
from app.presentations.repository import PresentationRecord, PresentationRepository
from app.presentations.schemas import (
    PlanElementResponse,
    PlanPresentationResponse,
    PositionJumpRequest,
)
from app.schemas_common import position_detail


def _page_url(course_id: int, version_number: int, page_number: int) -> str:
    return f"/api/cours/{course_id}/versions/{version_number}/pages/{page_number}"


def _append_insertion_elements(
    raw_elements: list[PlanElementResponse], items: list[InsertionRecord], start_position: int
) -> int:
    position = start_position
    for item in items:
        position += 1
        if item.item_type == "QUIZ":
            raw_elements.append(
                PlanElementResponse(
                    position=position,
                    type="QUIZ",
                    id_quiz=item.item_id,
                    titre=item.title,
                    apres_page=item.after_page,
                )
            )
        else:
            raw_elements.append(
                PlanElementResponse(
                    position=position,
                    type="LEADERBOARD",
                    id_leaderboard=item.item_id,
                    titre=item.title,
                    apres_page=item.after_page,
                )
            )
    return position


def _build_elements(
    course_id: int, version: VersionRecord, insertions: list[InsertionRecord]
) -> list[PlanElementResponse]:
    by_page: dict[int, list[InsertionRecord]] = {}
    for item in insertions:
        by_page.setdefault(item.after_page, []).append(item)

    raw_elements: list[PlanElementResponse] = []
    position = _append_insertion_elements(raw_elements, by_page.get(0, []), 0)
    for page in range(1, version.page_count + 1):
        position += 1
        raw_elements.append(
            PlanElementResponse(
                position=position,
                type="PAGE",
                numero_page=page,
                page_url=_page_url(course_id, version.version_number, page),
            )
        )
        position = _append_insertion_elements(raw_elements, by_page.get(page, []), position)

    next_page_url: str | None = None
    with_preload: list[PlanElementResponse] = []
    for element in reversed(raw_elements):
        with_preload.append(element.model_copy(update={"preload_page_url": next_page_url}))
        if element.type == "PAGE":
            next_page_url = element.page_url
    with_preload.reverse()
    return with_preload


class PresentationService:
    """Course presentation lifecycle, navigation, and protected page access."""

    def __init__(self, connection: sqlite3.Connection, storage: PdfStorage) -> None:
        self._conn = connection
        self._courses = CourseRepository(connection)
        self._presentations = PresentationRepository(connection)
        self._storage = storage

    def _require_owned_course(self, teacher_id: str, course_id: int) -> CourseRecord:
        course = self._courses.get_course(course_id)
        if course is None:
            raise CourseNotFoundError()
        if course.owner_ldap != teacher_id:
            raise AccessDeniedError()
        return course

    def _require_unfinished(
        self, teacher_id: str, course_id: int
    ) -> tuple[CourseRecord, PresentationRecord, VersionRecord, list[PlanElementResponse]]:
        course = self._require_owned_course(teacher_id, course_id)
        presentation = self._presentations.get_unfinished(course_id)
        if presentation is None:
            raise PresentationNotFoundError()
        version = self._courses.get_version_by_id(presentation.version_id)
        if version is None:
            raise InternalStorageError("Version de présentation introuvable")
        insertions = self._courses.list_insertions_for_version(version.id)
        elements = _build_elements(course.id, version, insertions)
        return course, presentation, version, elements

    @staticmethod
    def _build_response(
        course: CourseRecord,
        presentation: PresentationRecord,
        version: VersionRecord,
        elements: list[PlanElementResponse],
    ) -> PlanPresentationResponse:
        current = elements[presentation.current_position - 1]
        return PlanPresentationResponse(
            id_presentation=presentation.id,
            id_cours=course.id,
            titre=course.title,
            version=version.version_number,
            etat=presentation.state,
            position_courante=presentation.current_position,
            nb_elements=len(elements),
            element=current,
            elements=elements,
        )

    def start_or_resume(self, teacher_id: str, course_id: int) -> PlanPresentationResponse:
        """Start a presentation (freezing active version) or resume an unfinished one."""
        course = self._require_owned_course(teacher_id, course_id)
        if course.is_archived:
            raise CourseArchivedError()

        existing = self._presentations.get_unfinished(course_id)
        if existing is not None:
            version = self._courses.get_version_by_id(existing.version_id)
            if version is None:
                raise InternalStorageError("Version de présentation introuvable")
            if not self._storage.exists(course_id, version.version_number):
                raise PdfUnavailableError()
            if existing.state == "INTERROMPUE":
                with transaction(self._conn):
                    self._presentations.update_state(existing.id, "EN_PRESENTATION")
                existing = replace(existing, state="EN_PRESENTATION")
            elements = _build_elements(
                course.id, version, self._courses.list_insertions_for_version(version.id)
            )
            return self._build_response(course, existing, version, elements)

        version = self._courses.get_active_version(course_id)
        if version is None:
            raise InternalStorageError("Aucune version active pour ce cours")
        if not self._storage.exists(course_id, version.version_number):
            raise PdfUnavailableError()

        with transaction(self._conn):
            created = self._presentations.create(course_id, version.id)
        elements = _build_elements(
            course.id, version, self._courses.list_insertions_for_version(version.id)
        )
        return self._build_response(course, created, version, elements)

    def step(self, teacher_id: str, course_id: int, delta: int) -> PlanPresentationResponse:
        """Move forward (+1) or backward (-1), clamped to the plan boundaries."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        if presentation.state != "EN_PRESENTATION":
            raise PresentationStateError()
        target = max(1, min(len(elements), presentation.current_position + delta))
        if target != presentation.current_position:
            with transaction(self._conn):
                self._presentations.update_position(presentation.id, target)
            presentation = replace(presentation, current_position=target)
        return self._build_response(course, presentation, version, elements)

    def jump_to_position(
        self, teacher_id: str, course_id: int, payload: PositionJumpRequest
    ) -> PlanPresentationResponse:
        """Jump directly to a plan ``position`` or a PDF ``numeroPage``."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        if presentation.state != "EN_PRESENTATION":
            raise PresentationStateError()

        has_pos = payload.position is not None
        has_page = payload.numero_page is not None
        if has_pos == has_page:
            raise ValidationFailedError([position_detail("position")])

        if has_pos:
            assert payload.position is not None
            if not 1 <= payload.position <= len(elements):
                raise ValidationFailedError([position_detail("position")])
            target = payload.position
        else:
            assert payload.numero_page is not None
            matching = next(
                (
                    element.position
                    for element in elements
                    if element.type == "PAGE" and element.numero_page == payload.numero_page
                ),
                None,
            )
            if matching is None:
                raise ValidationFailedError([position_detail("numeroPage")])
            target = matching

        with transaction(self._conn):
            self._presentations.update_position(presentation.id, target)
        presentation = replace(presentation, current_position=target)
        return self._build_response(course, presentation, version, elements)

    def launch_quiz(self, teacher_id: str, course_id: int) -> PlanPresentationResponse:
        """Transition from ``EN_PRESENTATION`` on a QUIZ element to ``QUIZ_EN_COURS``."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        current = elements[presentation.current_position - 1]
        if presentation.state != "EN_PRESENTATION" or current.type != "QUIZ":
            raise PresentationStateError()
        with transaction(self._conn):
            self._presentations.update_state(presentation.id, "QUIZ_EN_COURS")
        presentation = replace(presentation, state="QUIZ_EN_COURS")
        return self._build_response(course, presentation, version, elements)

    def close_quiz(self, teacher_id: str, course_id: int) -> PlanPresentationResponse:
        """Close the running quiz and return to ``EN_PRESENTATION`` on the quiz element."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        if presentation.state != "QUIZ_EN_COURS":
            raise PresentationStateError()
        with transaction(self._conn):
            self._presentations.update_state(presentation.id, "EN_PRESENTATION")
        presentation = replace(presentation, state="EN_PRESENTATION")
        return self._build_response(course, presentation, version, elements)

    def interrupt(self, teacher_id: str, course_id: int) -> PlanPresentationResponse:
        """Mark an active presentation as interrupted (e.g. network drop)."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        with transaction(self._conn):
            self._presentations.update_state(presentation.id, "INTERROMPUE")
        presentation = replace(presentation, state="INTERROMPUE")
        return self._build_response(course, presentation, version, elements)

    def terminate(self, teacher_id: str, course_id: int) -> PlanPresentationResponse:
        """Close the presentation and release the course version lock."""
        course, presentation, version, elements = self._require_unfinished(teacher_id, course_id)
        ended_at = utc_now()
        with transaction(self._conn):
            self._presentations.update_state(presentation.id, "TERMINEE", ended_at=ended_at)
        presentation = replace(presentation, state="TERMINEE", ended_at=ended_at)
        return self._build_response(course, presentation, version, elements)

    def get_page_bytes(
        self, teacher_id: str, course_id: int, version_number: int, page_number: int
    ) -> bytes:
        """Return a single-page PDF if the caller owns the course and the page exists."""
        self._require_owned_course(teacher_id, course_id)
        version = self._courses.get_version_by_number(course_id, version_number)
        if version is None:
            raise VersionNotFoundError()
        if not 1 <= page_number <= version.page_count:
            raise PageNotFoundError()
        return self._storage.read_page(course_id, version_number, page_number)
