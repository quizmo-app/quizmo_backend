"""SQLite persistence layer for courses, versions, insertions and leaderboards."""

import json
import sqlite3
from collections.abc import Sequence

from app.courses.records import CourseRecord, InsertionRecord, VersionRecord
from app.database import inserted_id, utc_now


def _row_to_course(row: sqlite3.Row) -> CourseRecord:
    return CourseRecord(
        id=int(row["id"]),
        title=str(row["title"]),
        owner_ldap=str(row["owner_ldap"]),
        is_archived=bool(row["is_archived"]),
        created_at=str(row["created_at"]),
    )


def _row_to_version(row: sqlite3.Row) -> VersionRecord:
    fingerprints = tuple(json.loads(str(row["page_fingerprints"])))
    return VersionRecord(
        id=int(row["id"]),
        course_id=int(row["course_id"]),
        version_number=int(row["version_number"]),
        page_count=int(row["page_count"]),
        is_active=bool(row["is_active"]),
        page_fingerprints=fingerprints,
    )


def _row_to_insertion(row: sqlite3.Row) -> InsertionRecord:
    item_type = str(row["type_element"])
    item_id = int(row["id_quiz"]) if item_type == "QUIZ" else int(row["id_leaderboard"])
    return InsertionRecord(
        id=int(row["id"]),
        course_id=int(row["course_id"]),
        version_id=int(row["id_version"]),
        item_type=item_type,
        item_id=item_id,
        title=str(row["title"]),
        after_page=int(row["apres_page"]),
        ordre=int(row["ordre"]),
        page_fingerprint=str(row["empreinte"]),
    )


class CourseRepository:
    """Data access for courses, versions, insertions and leaderboards."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def get_course(self, course_id: int) -> CourseRecord | None:
        """Fetch a course by primary key."""
        row = self._conn.execute(
            "SELECT id, title, owner_ldap, is_archived, created_at FROM courses WHERE id = ?",
            (course_id,),
        ).fetchone()
        return _row_to_course(row) if row is not None else None

    def list_courses_for_owner(self, owner_ldap: str) -> list[CourseRecord]:
        """List the courses of one teacher, oldest first."""
        rows = self._conn.execute(
            "SELECT id, title, owner_ldap, is_archived, created_at FROM courses"
            " WHERE owner_ldap = ? ORDER BY id",
            (owner_ldap,),
        ).fetchall()
        return [_row_to_course(row) for row in rows]

    def get_active_version(self, course_id: int) -> VersionRecord | None:
        """Fetch the active version of a course."""
        row = self._conn.execute(
            "SELECT id, course_id, version_number, page_count, is_active, page_fingerprints"
            " FROM course_versions WHERE course_id = ? AND is_active = 1",
            (course_id,),
        ).fetchone()
        return _row_to_version(row) if row is not None else None

    def get_version_by_id(self, version_id: int) -> VersionRecord | None:
        """Fetch a course version by its primary key."""
        row = self._conn.execute(
            "SELECT id, course_id, version_number, page_count, is_active, page_fingerprints"
            " FROM course_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        return _row_to_version(row) if row is not None else None

    def get_version_by_number(self, course_id: int, version_number: int) -> VersionRecord | None:
        """Fetch a specific version number of a course."""
        row = self._conn.execute(
            "SELECT id, course_id, version_number, page_count, is_active, page_fingerprints"
            " FROM course_versions WHERE course_id = ? AND version_number = ?",
            (course_id, version_number),
        ).fetchone()
        return _row_to_version(row) if row is not None else None

    def list_insertions_for_version(self, version_id: int) -> list[InsertionRecord]:
        """List quiz and leaderboard insertions on a version in page/ordre order."""
        rows = self._conn.execute(
            """
            SELECT
                i.id, i.course_id, i.id_version, i.type_element, i.id_quiz, i.id_leaderboard,
                i.apres_page, i.ordre, i.empreinte,
                COALESCE(q.title, l.title, '') AS title
            FROM insertions i
            LEFT JOIN quizzes q ON q.id = i.id_quiz
            LEFT JOIN leaderboards l ON l.id = i.id_leaderboard
            WHERE i.id_version = ?
            ORDER BY i.apres_page ASC, i.ordre ASC, i.id ASC
            """,
            (version_id,),
        ).fetchall()
        return [_row_to_insertion(row) for row in rows]

    def create_course_with_v1(
        self, title: str, owner_ldap: str, page_count: int, fingerprints: Sequence[str]
    ) -> tuple[CourseRecord, VersionRecord]:
        """Insert a new course and its active version 1."""
        now = utc_now()
        cursor = self._conn.execute(
            "INSERT INTO courses (title, owner_ldap, is_archived, created_at) VALUES (?, ?, 0, ?)",
            (title, owner_ldap, now),
        )
        course_id = inserted_id(cursor)
        version_cursor = self._conn.execute(
            "INSERT INTO course_versions"
            " (course_id, version_number, page_count, is_active, page_fingerprints, created_at)"
            " VALUES (?, 1, ?, 1, ?, ?)",
            (course_id, page_count, json.dumps(list(fingerprints)), now),
        )
        version_id = inserted_id(version_cursor)
        course = CourseRecord(
            id=course_id, title=title, owner_ldap=owner_ldap, is_archived=False, created_at=now
        )
        version = VersionRecord(
            id=version_id,
            course_id=course_id,
            version_number=1,
            page_count=page_count,
            is_active=True,
            page_fingerprints=tuple(fingerprints),
        )
        return course, version

    def create_next_version(
        self,
        course_id: int,
        previous_version: VersionRecord,
        page_count: int,
        fingerprints: Sequence[str],
    ) -> VersionRecord:
        """Archive the previous active version and insert version k+1."""
        now = utc_now()
        next_number = previous_version.version_number + 1
        self._conn.execute(
            "UPDATE course_versions SET is_active = 0 WHERE id = ?", (previous_version.id,)
        )
        cursor = self._conn.execute(
            "INSERT INTO course_versions"
            " (course_id, version_number, page_count, is_active, page_fingerprints, created_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (course_id, next_number, page_count, json.dumps(list(fingerprints)), now),
        )
        version_id = inserted_id(cursor)
        return VersionRecord(
            id=version_id,
            course_id=course_id,
            version_number=next_number,
            page_count=page_count,
            is_active=True,
            page_fingerprints=tuple(fingerprints),
        )

    def set_course_archived(self, course_id: int, is_archived: bool) -> None:
        """Set or clear the archived flag on a course."""
        self._conn.execute(
            "UPDATE courses SET is_archived = ? WHERE id = ?",
            (1 if is_archived else 0, course_id),
        )

    def add_insertion(
        self,
        course_id: int,
        version_id: int,
        item_type: str,
        item_id: int,
        after_page: int,
        page_fingerprint: str,
    ) -> tuple[int, int]:
        """Insert a quiz or leaderboard placement, computing next ``ordre`` atomically."""
        quiz_id = item_id if item_type == "QUIZ" else None
        leaderboard_id = item_id if item_type == "LEADERBOARD" else None
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
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                version_id,
                item_type,
                quiz_id,
                leaderboard_id,
                after_page,
                ordre,
                page_fingerprint,
            ),
        )
        return inserted_id(cursor), ordre

    def create_leaderboard(self, course_id: int, title: str) -> int:
        """Insert a new leaderboard record and return its primary key."""
        cursor = self._conn.execute(
            "INSERT INTO leaderboards (course_id, title) VALUES (?, ?)",
            (course_id, title),
        )
        return inserted_id(cursor)
