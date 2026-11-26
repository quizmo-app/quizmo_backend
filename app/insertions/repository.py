"""SQLite persistence layer for QM-13 quiz insertions."""

import sqlite3
from dataclasses import dataclass

from app.database import inserted_id


@dataclass(frozen=True)
class QuizMetaRecord:
    """Quiz metadata needed to validate an insertion."""

    id: int
    course_id: int
    title: str
    question_count: int


@dataclass(frozen=True)
class InsertionListRow:
    """Row returned when listing insertions of a course version."""

    id: int
    type_element: str
    id_quiz: int | None
    quiz_title: str | None
    question_count: int | None
    apres_page: int
    ordre: int


class InsertionRepository:
    """Data access for QM-13 quiz insertions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def get_quiz_meta(self, quiz_id: int) -> QuizMetaRecord | None:
        """Return quiz ownership and question count, or None if not found."""
        row = self._conn.execute(
            """
            SELECT
                q.id,
                q.course_id,
                q.title,
                (SELECT COUNT(*) FROM questions qu WHERE qu.quiz_id = q.id) AS question_count
            FROM quizzes q
            WHERE q.id = ?
            """,
            (quiz_id,),
        ).fetchone()
        if row is None:
            return None
        return QuizMetaRecord(
            id=int(row["id"]),
            course_id=int(row["course_id"]),
            title=str(row["title"]),
            question_count=int(row["question_count"]),
        )

    def is_quiz_inserted(self, version_id: int, quiz_id: int) -> bool:
        """Whether ``quiz_id`` is already inserted into ``version_id``."""
        row = self._conn.execute(
            "SELECT 1 FROM insertions WHERE id_version = ? AND id_quiz = ? LIMIT 1",
            (version_id, quiz_id),
        ).fetchone()
        return row is not None

    def insert_quiz(
        self,
        course_id: int,
        version_id: int,
        quiz_id: int,
        after_page: int,
        fingerprint: str,
    ) -> tuple[int, int]:
        """Compute next ``ordre`` under transaction lock and insert the QUIZ row."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(ordre), 0) AS max_ordre"
            " FROM insertions WHERE id_version = ? AND apres_page = ?",
            (version_id, after_page),
        ).fetchone()
        ordre = (int(row["max_ordre"]) if row is not None else 0) + 1
        cursor = self._conn.execute(
            "INSERT INTO insertions"
            " (course_id, id_version, type_element, id_quiz, id_leaderboard,"
            " apres_page, ordre, empreinte)"
            " VALUES (?, ?, 'QUIZ', ?, NULL, ?, ?, ?)",
            (course_id, version_id, quiz_id, after_page, ordre, fingerprint),
        )
        return inserted_id(cursor), ordre

    def list_for_version(self, version_id: int) -> list[InsertionListRow]:
        """List insertions of ``version_id`` ordered by ``apres_page ASC, ordre ASC``."""
        rows = self._conn.execute(
            """
            SELECT
                i.id,
                i.type_element,
                i.id_quiz,
                i.apres_page,
                i.ordre,
                q.title AS quiz_title,
                (SELECT COUNT(*) FROM questions qu WHERE qu.quiz_id = q.id) AS question_count
            FROM insertions i
            LEFT JOIN quizzes q ON q.id = i.id_quiz
            WHERE i.id_version = ?
            ORDER BY i.apres_page ASC, i.ordre ASC, i.id ASC
            """,
            (version_id,),
        ).fetchall()
        return [
            InsertionListRow(
                id=int(row["id"]),
                type_element=str(row["type_element"]),
                id_quiz=int(row["id_quiz"]) if row["id_quiz"] is not None else None,
                quiz_title=str(row["quiz_title"]) if row["quiz_title"] is not None else None,
                question_count=(
                    int(row["question_count"]) if row["id_quiz"] is not None else None
                ),
                apres_page=int(row["apres_page"]),
                ordre=int(row["ordre"]),
            )
            for row in rows
        ]
