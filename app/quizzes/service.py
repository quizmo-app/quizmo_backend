"""Business logic for QM-12 quiz creation and retrieval."""

import sqlite3
from typing import Any

from pydantic import ValidationError

from app.courses.repository import CourseRepository
from app.database import transaction
from app.exceptions import (
    AccessDeniedError,
    CourseNotFoundError,
    InternalStorageError,
    QuizNotFoundError,
    ValidationFailedError,
)
from app.quizzes.repository import QuizRepository
from app.quizzes.schemas import (
    QuestionResponse,
    QuizCreateRequest,
    QuizDetailResponse,
    QuizSummaryResponse,
)
from app.schemas_common import InsertionInfo, detail_from_pydantic_error


class QuizService:
    """Create and read quizzes attached to courses."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._courses = CourseRepository(connection)
        self._quizzes = QuizRepository(connection)

    def _require_owned_course(self, teacher_id: str, course_id: int) -> None:
        course = self._courses.get_course(course_id)
        if course is None:
            raise CourseNotFoundError()
        if course.owner_ldap != teacher_id:
            raise AccessDeniedError()

    def create_quiz(
        self, teacher_id: str, course_id: int, raw_body: Any
    ) -> QuizDetailResponse:
        """Check access, parse & validate payload, and save quiz+questions+insertion atomically."""
        self._require_owned_course(teacher_id, course_id)
        version = self._courses.get_active_version(course_id)
        if version is None:
            raise InternalStorageError("Aucune version active pour ce cours")

        try:
            payload = QuizCreateRequest.model_validate(raw_body)
        except ValidationError as exc:
            details = [detail_from_pydantic_error(err) for err in exc.errors()]
            raise ValidationFailedError(details, message="Le quiz contient des erreurs") from exc

        details = payload.valider(version.page_count)
        if details:
            raise ValidationFailedError(details, message="Le quiz contient des erreurs")

        assert payload.titre is not None
        assert payload.duree_defaut is not None
        assert payload.apres_page is not None
        assert payload.questions is not None

        clean_title = payload.titre.strip()
        fingerprint = version.page_fingerprints[payload.apres_page - 1]

        with transaction(self._conn):
            quiz_id = self._quizzes.create_quiz(
                course_id=course_id,
                title=clean_title,
                default_duration=payload.duree_defaut,
                mode="NOTE",
            )
            insertion_id, _ = self._courses.add_insertion(
                course_id=course_id,
                version_id=version.id,
                item_type="QUIZ",
                item_id=quiz_id,
                after_page=payload.apres_page,
                page_fingerprint=fingerprint,
            )
            saved_questions = [
                self._quizzes.add_question(
                    quiz_id=quiz_id,
                    position=idx,
                    question_type=question.type,
                    statement=(question.enonce or "").strip(),
                    duration=question.duree or payload.duree_defaut,
                    configuration=question.normalized_configuration(),
                )
                for idx, question in enumerate(payload.questions, start=1)
            ]

        return QuizDetailResponse(
            id_quiz=quiz_id,
            id_cours=course_id,
            titre=clean_title,
            mode="NOTE",
            duree_defaut=payload.duree_defaut,
            insertion=InsertionInfo(
                id_insertion=insertion_id,
                id_version=version.id,
                apres_page=payload.apres_page,
            ),
            questions=[
                QuestionResponse(
                    id_question=item.id,
                    ordre=item.position,
                    type=item.type,
                    enonce=item.statement,
                    duree=item.duration,
                    configuration=item.configuration,
                )
                for item in saved_questions
            ],
        )

    def list_quizzes(self, teacher_id: str, course_id: int) -> list[QuizSummaryResponse]:
        """List quizzes for a course owned by ``teacher_id``."""
        self._require_owned_course(teacher_id, course_id)
        return [
            QuizSummaryResponse(
                id_quiz=item.id,
                titre=item.title,
                nb_questions=item.question_count,
                apres_page=item.after_page,
            )
            for item in self._quizzes.list_by_course(course_id)
        ]

    def get_quiz(self, teacher_id: str, quiz_id: int) -> QuizDetailResponse:
        """Read one quiz with its questions and correct answers."""
        result = self._quizzes.get_quiz(quiz_id)
        if result is None:
            raise QuizNotFoundError()
        quiz, questions = result
        self._require_owned_course(teacher_id, quiz.course_id)
        insertion = None
        if (
            quiz.insertion_id is not None
            and quiz.version_id is not None
            and quiz.after_page is not None
        ):
            insertion = InsertionInfo(
                id_insertion=quiz.insertion_id,
                id_version=quiz.version_id,
                apres_page=quiz.after_page,
            )
        return QuizDetailResponse(
            id_quiz=quiz.id,
            id_cours=quiz.course_id,
            titre=quiz.title,
            mode=quiz.mode,
            duree_defaut=quiz.default_duration,
            insertion=insertion,
            questions=[
                QuestionResponse(
                    id_question=item.id,
                    ordre=item.position,
                    type=item.type,
                    enonce=item.statement,
                    duree=item.duration,
                    configuration=item.configuration,
                )
                for item in questions
            ],
        )
