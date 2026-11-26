"""QM-12 acceptance tests: create and read quizzes (CU1.3 and CU1.4)."""

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.courses.records import CourseRecord, VersionRecord
from app.quizzes.repository import QuizRepository
from tests.conftest import TEACHER_A
from tests.helpers import valid_quiz_payload


def post_quiz(
    client: TestClient, headers: dict[str, str], course_id: int, payload: Any
) -> Any:
    """Send a quiz creation request."""
    return client.post(f"/api/cours/{course_id}/quiz", headers=headers, json=payload)


@pytest.fixture
def course_id(seed_course: Callable[..., tuple[CourseRecord, VersionRecord]]) -> int:
    """Create a 10-page course for quiz tests."""
    course, _ = seed_course(TEACHER_A, "Bases de données", 10)
    return course.id


def test_create_quiz_returns_201_with_location_and_full_body(
    client: TestClient, headers_a: dict[str, str], course_id: int, db: sqlite3.Connection
) -> None:
    response = post_quiz(client, headers_a, course_id, valid_quiz_payload(4))

    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/api/quiz/{body['idQuiz']}"
    assert body["idCours"] == course_id
    assert body["titre"] == "Les bases du SQL"
    assert body["mode"] == "NOTE"
    assert body["dureeDefaut"] == 30
    version_id = db.execute(
        "SELECT id FROM course_versions WHERE course_id = ? AND is_active = 1", (course_id,)
    ).fetchone()[0]
    assert body["insertion"]["apresPage"] == 4
    assert body["insertion"]["idVersion"] == version_id
    assert isinstance(body["insertion"]["idInsertion"], int)


def test_questions_are_numbered_in_submission_order_with_their_configuration(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    payload = valid_quiz_payload()
    body = post_quiz(client, headers_a, course_id, payload).json()

    assert [q["ordre"] for q in body["questions"]] == [1, 2, 3]
    assert [q["type"] for q in body["questions"]] == ["QCM", "LIBRE", "RELIER"]
    assert [q["duree"] for q in body["questions"]] == [30, 45, 60]
    for sent, stored in zip(payload["questions"], body["questions"], strict=True):
        assert stored["enonce"] == sent["enonce"]
        assert stored["configuration"] == sent["configuration"]
        assert isinstance(stored["idQuestion"], int)


def test_get_quiz_returns_the_same_object_with_correct_answers(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    created = post_quiz(client, headers_a, course_id, valid_quiz_payload()).json()
    response = client.get(f"/api/quiz/{created['idQuiz']}", headers=headers_a)
    assert response.status_code == 200
    assert response.json() == created
    assert response.json()["questions"][0]["configuration"]["options"][0]["correcte"] is True


def test_list_quizzes_returns_summaries(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    created = post_quiz(client, headers_a, course_id, valid_quiz_payload(4)).json()
    response = client.get(f"/api/cours/{course_id}/quiz", headers=headers_a)
    assert response.status_code == 200
    assert response.json() == [
        {"idQuiz": created["idQuiz"], "titre": "Les bases du SQL", "nbQuestions": 3, "apresPage": 4}
    ]


def test_missing_option_ids_and_defaults_are_filled_in(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    payload = valid_quiz_payload()
    payload["questions"] = [
        {
            "type": "QCM",
            "enonce": "Choisir",
            "duree": 20,
            "configuration": {"options": [{"libelle": "x", "correcte": True}, {"libelle": "y"}]},
        }
    ]
    body = post_quiz(client, headers_a, course_id, payload).json()
    assert body["questions"][0]["configuration"] == {
        "options": [
            {"id": "a", "libelle": "x", "correcte": True},
            {"id": "b", "libelle": "y", "correcte": False},
        ],
        "choixMultiple": False,
    }


def test_validation_error_returns_400_with_field_path_and_saves_nothing(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    payload = valid_quiz_payload()
    payload["questions"][0]["configuration"]["options"][0]["correcte"] = False

    response = post_quiz(client, headers_a, course_id, payload)

    assert response.status_code == 400
    assert response.json() == {
        "erreur": "VALIDATION",
        "message": "Le quiz contient des erreurs",
        "details": [
            {
                "champ": "questions[0].configuration.options",
                "code": "QCM_AUCUNE_BONNE_REPONSE",
                "message": "Un QCM doit avoir au moins une bonne réponse",
            }
        ],
    }
    assert client.get(f"/api/cours/{course_id}/quiz", headers=headers_a).json() == []


def test_every_problem_is_listed_in_details(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    payload = valid_quiz_payload(apres_page=99)
    payload["titre"] = ""
    payload["questions"][1]["configuration"]["reponsesAcceptees"] = []
    body = post_quiz(client, headers_a, course_id, payload).json()
    assert [(d["champ"], d["code"]) for d in body["details"]] == [
        ("titre", "CHAMP_OBLIGATOIRE"),
        ("apresPage", "POSITION_INVALIDE"),
        ("questions[1].configuration.reponsesAcceptees", "LIBRE_SANS_REPONSE_ACCEPTEE"),
    ]


def test_unknown_question_type_is_a_validation_error(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    payload = valid_quiz_payload()
    payload["questions"][0]["type"] = "VRAI_FAUX"
    response = post_quiz(client, headers_a, course_id, payload)
    assert response.status_code == 400
    detail = response.json()["details"][0]
    assert (detail["champ"], detail["code"]) == ("questions[0].type", "CHAMP_INVALIDE")


def test_wrong_json_types_never_leak_a_422(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    response = post_quiz(client, headers_a, course_id, {"titre": 123, "questions": "oops"})
    assert response.status_code == 400
    assert response.json()["erreur"] == "VALIDATION"
    assert {d["champ"] for d in response.json()["details"]} == {"titre", "questions"}


def test_malformed_json_is_a_validation_error(
    client: TestClient, headers_a: dict[str, str], course_id: int
) -> None:
    response = client.post(
        f"/api/cours/{course_id}/quiz",
        headers={**headers_a, "Content-Type": "application/json"},
        content=b"{not json",
    )
    assert response.status_code == 400
    assert response.json()["erreur"] == "VALIDATION"


def test_requests_without_credentials_get_401(client: TestClient, course_id: int) -> None:
    assert post_quiz(client, {}, course_id, valid_quiz_payload()).status_code == 401
    assert client.get(f"/api/cours/{course_id}/quiz").status_code == 401
    assert client.get("/api/quiz/1").status_code == 401


def test_cookie_authentication_is_accepted(
    client: TestClient, token_factory: Callable[..., str], course_id: int
) -> None:
    headers = {"Cookie": f"access_token={token_factory()}"}
    assert post_quiz(client, headers, course_id, valid_quiz_payload()).status_code == 201


def test_other_teacher_gets_403_on_every_route(
    client: TestClient,
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    course_id: int,
) -> None:
    created = post_quiz(client, headers_a, course_id, valid_quiz_payload()).json()

    forbidden = post_quiz(client, headers_b, course_id, valid_quiz_payload())
    assert forbidden.status_code == 403
    assert forbidden.json() == {"erreur": "ACCES_REFUSE", "message": "Accès refusé"}
    assert client.get(f"/api/cours/{course_id}/quiz", headers=headers_b).status_code == 403
    assert client.get(f"/api/quiz/{created['idQuiz']}", headers=headers_b).status_code == 403
    assert len(client.get(f"/api/cours/{course_id}/quiz", headers=headers_a).json()) == 1


@pytest.mark.parametrize("body", [{}, {"titre": 123}, valid_quiz_payload(apres_page=99)])
def test_access_control_runs_before_body_validation(
    client: TestClient, headers_b: dict[str, str], course_id: int, body: dict[str, Any]
) -> None:
    assert post_quiz(client, headers_b, course_id, body).status_code == 403


def test_unknown_course_and_quiz_get_404(client: TestClient, headers_a: dict[str, str]) -> None:
    missing_course = post_quiz(client, headers_a, 999999, valid_quiz_payload())
    assert missing_course.status_code == 404
    assert missing_course.json()["erreur"] == "COURS_INTROUVABLE"
    assert client.get("/api/cours/999999/quiz", headers=headers_a).status_code == 404
    missing_quiz = client.get("/api/quiz/999999", headers=headers_a)
    assert missing_quiz.status_code == 404
    assert missing_quiz.json()["erreur"] == "QUIZ_INTROUVABLE"


def test_storage_failure_rolls_back_everything_and_returns_500(
    client: TestClient,
    headers_a: dict[str, str],
    course_id: int,
    db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_add_question(*_args: Any, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(QuizRepository, "add_question", broken_add_question)

    response = post_quiz(client, headers_a, course_id, valid_quiz_payload())

    assert response.status_code == 500
    assert response.json()["erreur"] == "ERREUR_INTERNE"
    assert db.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM insertions").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
