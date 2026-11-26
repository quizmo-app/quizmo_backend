"""SQLite persistence layer for QM-14 course presentations."""

import sqlite3
from dataclasses import dataclass

from app.database import inserted_id, utc_now


@dataclass(frozen=True)
class PresentationRecord:
    """Stored presentation session."""

    id: int
    course_id: int
    version_id: int
    state: str
    current_position: int
    started_at: str
    ended_at: str | None


def _row_to_presentation(row: sqlite3.Row) -> PresentationRecord:
    return PresentationRecord(
        id=int(row["id"]),
        course_id=int(row["course_id"]),
        version_id=int(row["version_id"]),
        state=str(row["state"]),
        current_position=int(row["current_position"]),
        started_at=str(row["started_at"]),
        ended_at=str(row["ended_at"]) if row["ended_at"] is not None else None,
    )


class PresentationRepository:
    """Data access for presentation sessions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def get_unfinished(self, course_id: int) -> PresentationRecord | None:
        """Return the active, interrupted, or quiz-running presentation of a course."""
        row = self._conn.execute(
            "SELECT id, course_id, version_id, state, current_position, started_at, ended_at"
            " FROM presentations WHERE course_id = ? AND state <> 'TERMINEE'",
            (course_id,),
        ).fetchone()
        return _row_to_presentation(row) if row is not None else None

    def create(self, course_id: int, version_id: int) -> PresentationRecord:
        """Start a new presentation at position 1 freezing ``version_id``."""
        now = utc_now()
        cursor = self._conn.execute(
            "INSERT INTO presentations"
            " (course_id, version_id, state, current_position, started_at)"
            " VALUES (?, ?, 'EN_PRESENTATION', 1, ?)",
            (course_id, version_id, now),
        )
        return PresentationRecord(
            id=inserted_id(cursor),
            course_id=course_id,
            version_id=version_id,
            state="EN_PRESENTATION",
            current_position=1,
            started_at=now,
            ended_at=None,
        )

    def update_position(self, presentation_id: int, position: int) -> None:
        """Persist the current plan position."""
        self._conn.execute(
            "UPDATE presentations SET current_position = ? WHERE id = ?",
            (position, presentation_id),
        )

    def update_state(
        self, presentation_id: int, state: str, ended_at: str | None = None
    ) -> None:
        """Update presentation state and optional end timestamp."""
        self._conn.execute(
            "UPDATE presentations SET state = ?, ended_at = COALESCE(?, ended_at) WHERE id = ?",
            (state, ended_at, presentation_id),
        )
