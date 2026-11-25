"""QM-13 acceptance tests: insert an existing quiz into the current course version."""

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.courses.records import CourseRecord, VersionRecord
from app.insertions.repository import InsertionRepository
from app.main import create_app
from tests.conftest import TEACHER_A, TEACHER_B


def url(course_id: int, version_id: int) -> str:
    """Build the QM-13 insertions endpoint URL."""
    return f"/api/cours/{course_id}/versions/{version_id}/insertions"


def insert_quiz(
    client: TestClient,
    headers: dict[str, str],
    course_id: int,
    version_id: int,
    quiz_id: int,
    after_page: int,
) -> Any:
    """POST a quiz insertion request."""
    return client.post(
        url(course_id, version_id),
        headers=headers,
        json={"idQuiz": quiz_id, "apresPage": after_page},
    )


@pytest.fixture
def dataset(
    seed_course: Callable[..., tuple[CourseRecord, VersionRecord]],
    seed_next_version: Callable[[int, VersionRecord, int], VersionRecord],
    seed_uninserted_quiz: Callable[..., int],
) -> dict[str, Any]:
    """Exact QM-13 data set: BDD (v1 archived, v2 current, 10 pages) + Q1..Q6, Qvide, QB."""
    bdd, v1 = seed_course(TEACHER_A, "Bases de données", 10)
    v2 = seed_next_version(bdd.id, v1, 10)
    algo, _ = seed_course(TEACHER_B, "Algorithmique", 5)
    return {
        "course_id": bdd.id,
        "v1": v1,
        "v2": v2,
        "q1": seed_uninserted_quiz(bdd.id, "Q1", 3),
        "q2": seed_uninserted_quiz(bdd.id, "Q2", 1),
        "q3": seed_uninserted_quiz(bdd.id, "Q3", 2),
        "q4": seed_uninserted_quiz(bdd.id, "Q4", 1),
        "q5": seed_uninserted_quiz(bdd.id, "Q5", 1),
        "q6": seed_uninserted_quiz(bdd.id, "Q6", 1),
        "qvide": seed_uninserted_quiz(bdd.id, "Qvide", 0),
        "qb": seed_uninserted_quiz(algo.id, "QB", 1),
    }


def test_01_02_nominal_insertion_and_database_fields(
    client: TestClient,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    db: sqlite3.Connection,
) -> None:
    course_id = dataset["course_id"]
    v2: VersionRecord = dataset["v2"]

    response = insert_quiz(client, headers_a, course_id, v2.id, dataset["q1"], 4)

    assert response.status_code == 201
    body = response.json()
    assert body["apresPage"] == 4
    assert body["ordre"] == 1
    assert isinstance(body["idInsertion"], int)

    row = db.execute("SELECT * FROM insertions WHERE id = ?", (body["idInsertion"],)).fetchone()
    assert row is not None
    assert row["type_element"] == "QUIZ"
    assert row["id_quiz"] == dataset["q1"]
    assert row["id_version"] == v2.id
    assert row["apres_page"] == 4
    assert row["ordre"] == 1
    assert row["empreinte"] == v2.page_fingerprints[3]


def test_03_before_first_page_uses_position_zero_and_page_one_fingerprint(
    client: TestClient,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    db: sqlite3.Connection,
) -> None:
    v2: VersionRecord = dataset["v2"]
    response = insert_quiz(client, headers_a, dataset["course_id"], v2.id, dataset["q2"], 0)
    assert response.status_code == 201
    body = response.json()
    assert (body["apresPage"], body["ordre"]) == (0, 1)
    row = db.execute(
        "SELECT empreinte FROM insertions WHERE id = ?", (body["idInsertion"],)
    ).fetchone()
    assert row["empreinte"] == v2.page_fingerprints[0]


def test_04_after_last_page_is_accepted(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    v2: VersionRecord = dataset["v2"]
    response = insert_quiz(client, headers_a, dataset["course_id"], v2.id, dataset["q3"], 10)
    assert response.status_code == 201
    assert (response.json()["apresPage"], response.json()["ordre"]) == (10, 1)


def test_05_multiple_quizzes_after_same_page_get_incrementing_order(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    first = insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 4)
    second = insert_quiz(client, headers_a, course_id, v2_id, dataset["q4"], 4)
    assert first.status_code == 201
    assert second.status_code == 201
    assert (first.json()["ordre"], second.json()["ordre"]) == (1, 2)


def test_06_quiz_without_questions_is_refused_with_422(
    client: TestClient,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    db: sqlite3.Connection,
) -> None:
    v2_id = dataset["v2"].id
    response = insert_quiz(client, headers_a, dataset["course_id"], v2_id, dataset["qvide"], 6)
    assert response.status_code == 422
    assert response.json()["erreur"] == "QUIZ_INVALIDE"
    assert response.json()["action"]
    assert db.execute("SELECT COUNT(*) FROM insertions").fetchone()[0] == 0


def test_07_already_inserted_quiz_is_refused_with_409(
    client: TestClient,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    db: sqlite3.Connection,
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    assert insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 4).status_code == 201

    duplicate = insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 7)

    assert duplicate.status_code == 409
    assert duplicate.json()["erreur"] == "QUIZ_DEJA_INSERE"
    assert duplicate.json()["action"]
    rows = db.execute(
        "SELECT apres_page FROM insertions WHERE id_quiz = ?", (dataset["q1"],)
    ).fetchall()
    assert [row["apres_page"] for row in rows] == [4]


def test_08_expired_or_missing_session_returns_401_then_relogin_succeeds(
    client: TestClient,
    token_factory: Callable[..., str],
    dataset: dict[str, Any],
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id

    anonymous = insert_quiz(client, {}, course_id, v2_id, dataset["q5"], 2)
    assert anonymous.status_code == 401
    assert anonymous.json()["erreur"] == "SESSION_EXPIREE"
    assert anonymous.json()["action"]

    expired = token_factory(expires_delta=timedelta(seconds=-5))
    expired_resp = insert_quiz(
        client, {"Cookie": f"access_token={expired}"}, course_id, v2_id, dataset["q5"], 2
    )
    assert expired_resp.status_code == 401
    assert expired_resp.json()["erreur"] == "SESSION_EXPIREE"

    reconnected = insert_quiz(
        client, {"Cookie": f"access_token={token_factory()}"}, course_id, v2_id, dataset["q5"], 2
    )
    assert reconnected.status_code == 201


def test_09_database_unavailable_returns_503_and_saves_nothing(
    client: TestClient,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_db(*_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError("connection refused")

    monkeypatch.setattr(InsertionRepository, "insert_quiz", fail_db)
    response = insert_quiz(
        client, headers_a, dataset["course_id"], dataset["v2"].id, dataset["q6"], 3
    )
    assert response.status_code == 503
    assert response.json()["erreur"] == "BDD_INDISPONIBLE"
    expected_msg = "Réessayez dans quelques minutes ou prévenez l'administrateur"
    assert expected_msg in response.json()["message"]
    assert db.execute("SELECT COUNT(*) FROM insertions").fetchone()[0] == 0


def test_10_chained_scenario_and_sorted_list(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    for quiz_key, page in (("q1", 4), ("q2", 0), ("q3", 10), ("q4", 4), ("q5", 2)):
        created = insert_quiz(client, headers_a, course_id, v2_id, dataset[quiz_key], page)
        assert created.status_code == 201

    response = client.get(url(course_id, v2_id), headers=headers_a)
    assert response.status_code == 200
    items = response.json()
    assert [(item["idQuiz"], item["apresPage"], item["ordre"]) for item in items] == [
        (dataset["q2"], 0, 1),
        (dataset["q5"], 2, 1),
        (dataset["q1"], 4, 1),
        (dataset["q4"], 4, 2),
        (dataset["q3"], 10, 1),
    ]
    assert items[2]["quiz"] == {"idQuiz": dataset["q1"], "titre": "Q1", "nbQuestions": 3}


@pytest.mark.parametrize("bad_page", [-1, 11])
def test_11_12_page_out_of_bounds_returns_400(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any], bad_page: int
) -> None:
    response = insert_quiz(
        client, headers_a, dataset["course_id"], dataset["v2"].id, dataset["q6"], bad_page
    )
    assert response.status_code == 400
    assert response.json()["erreur"] == "PAGE_INVALIDE"
    assert response.json()["action"]


def test_13_quiz_from_another_course_returns_422(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    response = insert_quiz(
        client, headers_a, dataset["course_id"], dataset["v2"].id, dataset["qb"], 3
    )
    assert response.status_code == 422
    assert response.json()["erreur"] == "QUIZ_INVALIDE"


def test_14_archived_version_returns_409(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    response = insert_quiz(
        client, headers_a, dataset["course_id"], dataset["v1"].id, dataset["q6"], 3
    )
    assert response.status_code == 409
    assert response.json()["erreur"] == "VERSION_NON_COURANTE"
    assert response.json()["action"]


def test_15_other_teacher_gets_403_on_post_and_get(
    client: TestClient, headers_b: dict[str, str], dataset: dict[str, Any]
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    post_resp = insert_quiz(client, headers_b, course_id, v2_id, dataset["q6"], 3)
    get_resp = client.get(url(course_id, v2_id), headers=headers_b)
    assert post_resp.status_code == 403
    assert post_resp.json()["erreur"] == "ACCES_REFUSE"
    assert get_resp.status_code == 403
    assert get_resp.json()["erreur"] == "ACCES_REFUSE"


def test_16_missing_course_version_or_quiz_returns_404(
    client: TestClient, headers_a: dict[str, str], dataset: dict[str, Any]
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    cases = [
        (999999, v2_id, dataset["q6"]),
        (course_id, 999999, dataset["q6"]),
        (course_id, v2_id, 999999),
    ]
    for cid, vid, qid in cases:
        resp = insert_quiz(client, headers_a, cid, vid, qid, 3)
        assert resp.status_code == 404
        assert resp.json()["erreur"] == "RESSOURCE_INTROUVABLE"
        assert resp.json()["action"]


def test_17_control_order_ownership_before_version_and_page_before_duplicate(
    client: TestClient,
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    dataset: dict[str, Any],
) -> None:
    course_id = dataset["course_id"]
    v1_id = dataset["v1"].id
    v2_id = dataset["v2"].id

    # Owner is checked before active-version check
    first = insert_quiz(client, headers_b, course_id, v1_id, dataset["q6"], 3)
    assert first.status_code == 403
    assert first.json()["erreur"] == "ACCES_REFUSE"

    # Page bounds are checked before duplicate check
    assert insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 4).status_code == 201
    second = insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 99)
    assert second.status_code == 400
    assert second.json()["erreur"] == "PAGE_INVALIDE"


def test_18_concurrent_insertions_assign_distinct_orders(
    client: TestClient,
    settings: Settings,
    headers_a: dict[str, str],
    dataset: dict[str, Any],
    seed_uninserted_quiz: Callable[..., int],
) -> None:
    course_id = dataset["course_id"]
    v2_id = dataset["v2"].id
    assert insert_quiz(client, headers_a, course_id, v2_id, dataset["q1"], 4).status_code == 201
    assert insert_quiz(client, headers_a, course_id, v2_id, dataset["q4"], 4).status_code == 201
    q7 = seed_uninserted_quiz(course_id, "Q7", 1)
    q8 = seed_uninserted_quiz(course_id, "Q8", 1)

    app_instance = create_app(settings)

    def worker(quiz_id: int) -> tuple[int, dict[str, Any]]:
        with TestClient(app_instance) as thread_client:
            resp = insert_quiz(thread_client, headers_a, course_id, v2_id, quiz_id, 4)
            return resp.status_code, dict(resp.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (q7, q8)))

    assert all(status_code == 201 for status_code, _ in results), results
    orders = sorted(body["ordre"] for _, body in results)
    assert orders == [3, 4]
    listed = client.get(url(course_id, v2_id), headers=headers_a).json()
    page4_orders = [(item["idQuiz"], item["ordre"]) for item in listed if item["apresPage"] == 4]
    assert [order for _, order in page4_orders] == [1, 2, 3, 4]
