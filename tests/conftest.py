"""Shared fixtures: isolated application, database, storage and authentication."""

import sqlite3
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_handler import create_access_token
from app.config import Settings
from app.courses.pdf_storage import PdfStorage
from app.courses.records import CourseRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.main import create_app
from app.quizzes.repository import QuizRepository
from tests.helpers import make_pdf_bytes, valid_quiz_payload

TEACHER_A = "prof_a"
TEACHER_B = "prof_b"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing to a throw-away database and storage folder."""
    return Settings(
        secret_key="test-secret-key-0123456789-abcdefghijklmnop",
        database_path=tmp_path / "db" / "quizmo.db",
        storage_dir=tmp_path / "storage",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Test client with the application lifespan running (schema created)."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def token_factory(settings: Settings) -> Callable[..., str]:
    """Create signed JWTs for arbitrary teachers."""

    def _make(teacher_id: str = TEACHER_A, expires_delta: timedelta | None = None) -> str:
        return create_access_token(teacher_id, settings, expires_delta=expires_delta)

    return _make


@pytest.fixture
def headers_a(token_factory: Callable[..., str]) -> dict[str, str]:
    """Bearer headers of teacher A."""
    return {"Authorization": f"Bearer {token_factory(TEACHER_A)}"}


@pytest.fixture
def headers_b(token_factory: Callable[..., str]) -> dict[str, str]:
    """Bearer headers of teacher B."""
    return {"Authorization": f"Bearer {token_factory(TEACHER_B)}"}


@pytest.fixture
def db(settings: Settings, client: TestClient) -> Iterator[sqlite3.Connection]:
    """Direct (autocommit) connection used to inspect or seed the database."""
    assert client is not None
    connection = sqlite3.connect(settings.database_path, timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


@pytest.fixture
def seed_course(
    db: sqlite3.Connection, settings: Settings
) -> Callable[..., tuple[CourseRecord, VersionRecord]]:
    """Seed a course with version 1 and its PDF file on disk."""

    def _seed(
        owner: str = TEACHER_A, title: str = "Cours", pages: int = 10
    ) -> tuple[CourseRecord, VersionRecord]:
        storage = PdfStorage(settings.storage_dir)
        pdf = make_pdf_bytes(pages)
        info = storage.inspect(pdf)
        course, version = CourseRepository(db).create_course_with_v1(
            title, owner, info.page_count, info.fingerprints
        )
        storage.save(course.id, version.version_number, pdf)
        return course, version

    return _seed


@pytest.fixture
def seed_next_version(
    db: sqlite3.Connection, settings: Settings
) -> Callable[[int, VersionRecord, int], VersionRecord]:
    """Archive ``previous`` and create the next active version with its PDF file."""

    def _next(course_id: int, previous: VersionRecord, pages: int = 10) -> VersionRecord:
        storage = PdfStorage(settings.storage_dir)
        pdf = make_pdf_bytes(pages)
        info = storage.inspect(pdf)
        version = CourseRepository(db).create_next_version(
            course_id, previous, info.page_count, info.fingerprints
        )
        storage.save(course_id, version.version_number, pdf)
        return version

    return _next


@pytest.fixture
def seed_uninserted_quiz(db: sqlite3.Connection) -> Callable[..., int]:
    """Seed a quiz with ``num_questions`` questions and no insertion yet."""

    def _seed(course_id: int, title: str = "Quiz", num_questions: int = 1) -> int:
        repo = QuizRepository(db)
        quiz_id = repo.create_quiz(course_id, title, 30)
        for index in range(1, num_questions + 1):
            repo.add_question(
                quiz_id=quiz_id,
                position=index,
                question_type="LIBRE",
                statement=f"Question {index} ?",
                duration=30,
                configuration={
                    "reponsesAcceptees": ["oui"],
                    "sensibleCasse": False,
                    "note": True,
                },
            )
        return quiz_id

    return _seed


@pytest.fixture
def add_quiz(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Create the nominal QM-12 quiz after a given page and return the response body."""

    def _add(headers: dict[str, str], course_id: int, after_page: int = 4) -> dict[str, Any]:
        response = client.post(
            f"/api/cours/{course_id}/quiz", headers=headers, json=valid_quiz_payload(after_page)
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    return _add


@pytest.fixture
def add_leaderboard(db: sqlite3.Connection) -> Callable[..., dict[str, int]]:
    """Seed a leaderboard and its insertion on the active version of a course."""

    def _add(course_id: int, after_page: int = 8, title: str = "Classement") -> dict[str, int]:
        repo = CourseRepository(db)
        version = repo.get_active_version(course_id)
        assert version is not None
        leaderboard_id = repo.create_leaderboard(course_id, title)
        fingerprint = version.page_fingerprints[max(0, after_page - 1)]
        insertion_id, _ = repo.add_insertion(
            course_id=course_id,
            version_id=version.id,
            item_type="LEADERBOARD",
            item_id=leaderboard_id,
            after_page=after_page,
            page_fingerprint=fingerprint,
        )
        return {"idLeaderboard": leaderboard_id, "idInsertion": insertion_id}

    return _add


@pytest.fixture
def bdd_course(
    seed_course: Callable[..., tuple[CourseRecord, VersionRecord]],
    add_quiz: Callable[..., dict[str, Any]],
    add_leaderboard: Callable[..., dict[str, int]],
    headers_a: dict[str, str],
) -> dict[str, int]:
    """QM-14 data set: 10 pages, quiz Q1 after page 4, leaderboard L1 after page 8."""
    course, _ = seed_course(TEACHER_A, "Bases de données", 10)
    quiz = add_quiz(headers_a, course.id, 4)
    leaderboard = add_leaderboard(course.id, 8)
    return {
        "id": course.id,
        "quiz_id": int(quiz["idQuiz"]),
        "leaderboard_id": leaderboard["idLeaderboard"],
    }
