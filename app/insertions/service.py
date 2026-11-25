"""Business logic for QM-13 quiz insertions in a course version."""

import sqlite3
from typing import Any

from app.courses.records import CourseRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.database import transaction
from app.exceptions import (
    AccessDeniedError,
    DatabaseUnavailableError,
    InternalStorageError,
    InvalidPageError,
    InvalidQuizForInsertionError,
    NonCurrentVersionError,
    QuizAlreadyInsertedError,
    ResourceMissingError,
)
from app.insertions.repository import InsertionRepository, QuizMetaRecord
from app.insertions.schemas import (
    InsertedQuizSummary,
    InsertionCreateResponse,
    InsertionItemResponse,
)


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class InsertionService:
    """Validate and persist quiz insertions on the active course version."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._courses = CourseRepository(connection)
        self._insertions = InsertionRepository(connection)

    def _load_course_and_version(
        self, course_id: int, version_id: int
    ) -> tuple[CourseRecord, VersionRecord]:
        course = self._courses.get_course(course_id)
        if course is None:
            raise ResourceMissingError()
        version = self._courses.get_version_by_id(version_id)
        if version is None or version.course_id != course_id:
            raise ResourceMissingError()
        return course, version

    def insert_quiz(
        self, teacher_id: str, course_id: int, version_id: int, raw_body: Any
    ) -> InsertionCreateResponse:
        """Check controls in strict QM-13 order and insert the quiz atomically."""
        if not isinstance(raw_body, dict):
            raw_body = {}
        raw_quiz_id = raw_body.get("idQuiz")
        raw_after_page = raw_body.get("apresPage")

        try:
            course, version = self._load_course_and_version(course_id, version_id)
            quiz: QuizMetaRecord | None = None
            if _is_strict_int(raw_quiz_id):
                quiz = self._insertions.get_quiz_meta(int(raw_quiz_id))
                if quiz is None:
                    raise ResourceMissingError()
        except sqlite3.Error as exc:
            raise DatabaseUnavailableError() from exc

        if course.owner_ldap != teacher_id:
            raise AccessDeniedError(
                action="Ouvrir un de ses propres cours",
            )
        if not version.is_active:
            raise NonCurrentVersionError()
        if not _is_strict_int(raw_after_page) or not 0 <= int(raw_after_page) <= version.page_count:
            raise InvalidPageError()
        after_page = int(raw_after_page)

        if quiz is None or quiz.course_id != course_id or quiz.question_count < 1:
            raise InvalidQuizForInsertionError()

        anchor_index = 0 if after_page == 0 else after_page - 1
        fingerprint = version.page_fingerprints[anchor_index]

        try:
            with transaction(self._conn):
                if self._insertions.is_quiz_inserted(version.id, quiz.id):
                    raise QuizAlreadyInsertedError()
                try:
                    insertion_id, ordre = self._insertions.insert_quiz(
                        course_id=course_id,
                        version_id=version.id,
                        quiz_id=quiz.id,
                        after_page=after_page,
                        fingerprint=fingerprint,
                    )
                except sqlite3.IntegrityError as exc:
                    raise QuizAlreadyInsertedError() from exc
        except (sqlite3.Error, InternalStorageError) as exc:
            raise DatabaseUnavailableError() from exc

        return InsertionCreateResponse(
            id_insertion=insertion_id,
            apres_page=after_page,
            ordre=ordre,
        )

    def list_insertions(
        self, teacher_id: str, course_id: int, version_id: int
    ) -> list[InsertionItemResponse]:
        """Return insertions for ``version_id`` sorted by ``apresPage`` then ``ordre``."""
        try:
            course, version = self._load_course_and_version(course_id, version_id)
            if course.owner_ldap != teacher_id:
                raise AccessDeniedError(
                    action="Ouvrir un de ses propres cours",
                )
            rows = self._insertions.list_for_version(version.id)
        except sqlite3.Error as exc:
            raise DatabaseUnavailableError() from exc

        return [
            InsertionItemResponse(
                id_insertion=row.id,
                type_element=row.type_element,
                id_quiz=row.id_quiz,
                quiz=(
                    InsertedQuizSummary(
                        id_quiz=row.id_quiz,
                        titre=row.quiz_title or "",
                        nb_questions=row.question_count or 0,
                    )
                    if row.id_quiz is not None
                    else None
                ),
                apres_page=row.apres_page,
                ordre=row.ordre,
            )
            for row in rows
        ]
