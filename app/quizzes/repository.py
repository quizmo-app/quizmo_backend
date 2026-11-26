"""SQLite persistence layer for quizzes and questions."""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.database import inserted_id


@dataclass(frozen=True)
class QuestionRecord:
    """Stored question row."""

    id: int
    quiz_id: int
    position: int
    type: str
    statement: str
    duration: int
    configuration: dict[str, Any]


@dataclass(frozen=True)
class QuizRecord:
    """Stored quiz row together with its optional active-version insertion metadata."""

    id: int
    course_id: int
    title: str
    mode: str
    default_duration: int
    insertion_id: int | None
    version_id: int | None
    after_page: int | None


@dataclass(frozen=True)
class QuizSummaryRecord:
    """Summary row for ``GET /api/cours/{idCours}/quiz``."""

    id: int
    title: str
    question_count: int
    after_page: int | None


class QuizRepository:
    """Data access for quizzes and questions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def create_quiz(
        self, course_id: int, title: str, default_duration: int, mode: str = "NOTE"
    ) -> int:
        """Insert a quiz row and return its id."""
        cursor = self._conn.execute(
            "INSERT INTO quizzes (course_id, title, mode, default_duration) VALUES (?, ?, ?, ?)",
            (course_id, title, mode, default_duration),
        )
        return inserted_id(cursor)

    def add_question(
        self,
        quiz_id: int,
        position: int,
        question_type: str,
        statement: str,
        duration: int,
        configuration: dict[str, Any],
    ) -> QuestionRecord:
        """Insert one question row and return its immutable record."""
        cursor = self._conn.execute(
            "INSERT INTO questions"
            " (quiz_id, position, type, statement, duration, configuration)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (quiz_id, position, question_type, statement, duration, json.dumps(configuration)),
        )
        question_id = inserted_id(cursor)
        return QuestionRecord(
            id=question_id,
            quiz_id=quiz_id,
            position=position,
            type=question_type,
            statement=statement,
            duration=duration,
            configuration=configuration,
        )

    def list_by_course(self, course_id: int) -> list[QuizSummaryRecord]:
        """List quizzes of a course with question counts and active-version page position."""
        rows = self._conn.execute(
            """
            SELECT
                q.id,
                q.title,
                (SELECT COUNT(*) FROM questions qu WHERE qu.quiz_id = q.id) AS question_count,
                i.apres_page AS after_page
            FROM quizzes q
            LEFT JOIN course_versions v ON v.course_id = q.course_id AND v.is_active = 1
            LEFT JOIN insertions i ON i.id_quiz = q.id AND i.id_version = v.id
            WHERE q.course_id = ?
            ORDER BY COALESCE(i.apres_page, 2147483647) ASC, q.id ASC
            """,
            (course_id,),
        ).fetchall()
        return [
            QuizSummaryRecord(
                id=int(row["id"]),
                title=str(row["title"]),
                question_count=int(row["question_count"]),
                after_page=int(row["after_page"]) if row["after_page"] is not None else None,
            )
            for row in rows
        ]

    def get_quiz(self, quiz_id: int) -> tuple[QuizRecord, list[QuestionRecord]] | None:
        """Fetch a quiz, its optional active-version insertion, and its ordered questions."""
        quiz_row = self._conn.execute(
            """
            SELECT
                q.id, q.course_id, q.title, q.mode, q.default_duration,
                i.id AS insertion_id, i.id_version AS version_id, i.apres_page AS after_page
            FROM quizzes q
            LEFT JOIN course_versions v ON v.course_id = q.course_id AND v.is_active = 1
            LEFT JOIN insertions i ON i.id_quiz = q.id AND i.id_version = v.id
            WHERE q.id = ?
            """,
            (quiz_id,),
        ).fetchone()
        if quiz_row is None:
            return None
        question_rows = self._conn.execute(
            "SELECT id, quiz_id, position, type, statement, duration, configuration"
            " FROM questions WHERE quiz_id = ? ORDER BY position ASC",
            (quiz_id,),
        ).fetchall()
        quiz = QuizRecord(
            id=int(quiz_row["id"]),
            course_id=int(quiz_row["course_id"]),
            title=str(quiz_row["title"]),
            mode=str(quiz_row["mode"]),
            default_duration=int(quiz_row["default_duration"]),
            insertion_id=(
                int(quiz_row["insertion_id"]) if quiz_row["insertion_id"] is not None else None
            ),
            version_id=(
                int(quiz_row["version_id"]) if quiz_row["version_id"] is not None else None
            ),
            after_page=(
                int(quiz_row["after_page"]) if quiz_row["after_page"] is not None else None
            ),
        )
        questions = [
            QuestionRecord(
                id=int(row["id"]),
                quiz_id=int(row["quiz_id"]),
                position=int(row["position"]),
                type=str(row["type"]),
                statement=str(row["statement"]),
                duration=int(row["duration"]),
                configuration=json.loads(str(row["configuration"])),
            )
            for row in question_rows
        ]
        return quiz, questions
