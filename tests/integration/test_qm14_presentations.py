"""QM-14 acceptance tests: present a course page by page."""

import json
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.courses.pdf_storage import PdfStorage
from app.courses.repository import CourseRepository
from tests.helpers import make_pdf_bytes, read_single_page_width

EXPECTED_PLAN = ["P1", "P2", "P3", "P4", "Q1", "P5", "P6", "P7", "P8", "L1", "P9", "P10"]


def url(course_id: int, suffix: str = "") -> str:
    """Build a presentation endpoint path."""
    return f"/cours/{course_id}/presentation{suffix}"


def describe(elements: list[dict[str, Any]], course: dict[str, int]) -> list[str]:
    """Map plan elements to compact labels (P1..P10, Q1, L1)."""
    labels = []
    for element in elements:
        if element["type"] == "PAGE":
            labels.append(f"P{element['numeroPage']}")
        elif element["type"] == "QUIZ":
            labels.append("Q1" if element["idQuiz"] == course["quiz_id"] else "Q?")
        else:
            labels.append("L1" if element["idLeaderboard"] == course["leaderboard_id"] else "L?")
    return labels


def start(client: TestClient, headers: dict[str, str], course: dict[str, int]) -> dict[str, Any]:
    """Start or resume a course presentation."""
    response = client.get(url(course["id"]), headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def go_to(
    client: TestClient, headers: dict[str, str], course: dict[str, int], **target: int
) -> dict[str, Any]:
    """Jump to a target position or page."""
    response = client.put(url(course["id"], "/position"), headers=headers, json=target)
    assert response.status_code == 200, response.text
    return dict(response.json())


def act(client: TestClient, headers: dict[str, str], course: dict[str, int], action: str) -> Any:
    """POST a presentation state/navigation action."""
    return client.post(url(course["id"], action), headers=headers)


def page_url(course: dict[str, int], page: int, version: int = 1) -> str:
    """Build the API URL for a single versioned page."""
    return f"/api/cours/{course['id']}/versions/{version}/pages/{page}"


# --- CA1: plan --------------------------------------------------------------------------


def test_01_start_shows_page_one(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    body = start(client, headers_a, bdd_course)
    assert body["etat"] == "EN_PRESENTATION"
    assert body["positionCourante"] == 1
    assert body["nbElements"] == 12
    assert body["version"] == 1
    assert body["titre"] == "Bases de données"
    assert body["element"]["type"] == "PAGE"
    assert body["element"]["numeroPage"] == 1
    assert body["element"]["pageUrl"] == page_url(bdd_course, 1)


def test_02_plan_interleaves_quiz_and_leaderboard_in_order(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    body = start(client, headers_a, bdd_course)
    assert describe(body["elements"], bdd_course) == EXPECTED_PLAN
    assert [element["position"] for element in body["elements"]] == list(range(1, 13))
    quiz = body["elements"][4]
    assert (quiz["titre"], quiz["apresPage"]) == ("Les bases du SQL", 4)
    leaderboard = body["elements"][9]
    assert (leaderboard["titre"], leaderboard["apresPage"]) == ("Classement", 8)


def test_plan_is_also_served_under_the_api_prefix(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    first = start(client, headers_a, bdd_course)
    response = client.get(f"/api/cours/{bdd_course['id']}/presentation", headers=headers_a)
    assert response.status_code == 200
    assert response.json()["elements"] == first["elements"]


# --- CA2: navigation --------------------------------------------------------------------


def test_03_next_and_previous_move_one_element(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    act(client, headers_a, bdd_course, "/suivant")
    third = act(client, headers_a, bdd_course, "/suivant").json()
    assert (third["positionCourante"], third["element"]["numeroPage"]) == (3, 3)
    second = act(client, headers_a, bdd_course, "/precedent").json()
    assert (second["positionCourante"], second["element"]["numeroPage"]) == (2, 2)


def test_04_direct_access_by_page_number_or_position(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    seventh = go_to(client, headers_a, bdd_course, numeroPage=7)
    assert seventh["element"]["numeroPage"] == 7
    assert seventh["positionCourante"] == 8
    fifth = go_to(client, headers_a, bdd_course, position=5)
    assert fifth["element"]["type"] == "QUIZ"


@pytest.mark.parametrize(
    "target",
    [
        {"position": 0},
        {"position": 13},
        {"numeroPage": 0},
        {"numeroPage": 11},
        {},
        {"position": 1, "numeroPage": 1},
    ],
)
def test_invalid_jump_is_refused_and_position_is_kept(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int], target: dict
) -> None:
    start(client, headers_a, bdd_course)
    response = client.put(url(bdd_course["id"], "/position"), headers=headers_a, json=target)
    assert response.status_code == 400
    assert response.json()["erreur"] == "VALIDATION"
    assert response.json()["details"][0]["code"] == "POSITION_INVALIDE"
    assert start(client, headers_a, bdd_course)["positionCourante"] == 1


def test_05_plan_boundaries_keep_the_current_element(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    before_start = act(client, headers_a, bdd_course, "/precedent")
    assert before_start.status_code == 200
    assert before_start.json()["element"]["numeroPage"] == 1

    last = go_to(client, headers_a, bdd_course, position=12)
    assert last["element"]["numeroPage"] == 10
    after_end = act(client, headers_a, bdd_course, "/suivant")
    assert after_end.status_code == 200
    assert after_end.json()["positionCourante"] == 12
    assert after_end.json()["element"]["numeroPage"] == 10


def test_06_next_page_url_is_provided_for_preloading(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    fifth = go_to(client, headers_a, bdd_course, numeroPage=5)
    assert fifth["element"]["preloadPageUrl"] == page_url(bdd_course, 6)

    quiz = go_to(client, headers_a, bdd_course, position=5)
    assert quiz["element"]["preloadPageUrl"] == page_url(bdd_course, 5)

    last = go_to(client, headers_a, bdd_course, position=12)
    assert last["element"]["preloadPageUrl"] is None

    elements = start(client, headers_a, bdd_course)["elements"]
    assert elements[3]["preloadPageUrl"] == page_url(bdd_course, 5)
    assert elements[11]["preloadPageUrl"] is None


# --- CA3: quiz and leaderboard pages ----------------------------------------------------


def test_07_quiz_page_can_launch_and_close_a_quiz(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    quiz_page = go_to(client, headers_a, bdd_course, position=5)
    assert quiz_page["element"]["idQuiz"] == bdd_course["quiz_id"]

    launched = act(client, headers_a, bdd_course, "/quiz/lancer").json()
    assert launched["etat"] == "QUIZ_EN_COURS"
    assert launched["element"]["type"] == "QUIZ"
    blocked = act(client, headers_a, bdd_course, "/suivant")
    assert blocked.status_code == 409
    assert blocked.json()["erreur"] == "PRESENTATION_ETAT_INVALIDE"

    closed = act(client, headers_a, bdd_course, "/quiz/cloturer").json()
    assert closed["etat"] == "EN_PRESENTATION"
    assert closed["positionCourante"] == 5
    assert closed["element"]["type"] == "QUIZ"


def test_quiz_cannot_be_launched_from_a_course_page_or_closed_when_not_running(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    assert act(client, headers_a, bdd_course, "/quiz/lancer").status_code == 409
    assert act(client, headers_a, bdd_course, "/quiz/cloturer").status_code == 409


def test_08_leaderboard_page(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    body = go_to(client, headers_a, bdd_course, position=10)
    assert body["element"]["type"] == "LEADERBOARD"
    assert body["element"]["idLeaderboard"] == bdd_course["leaderboard_id"]
    assert act(client, headers_a, bdd_course, "/quiz/lancer").status_code == 409


# --- CA4: resume ------------------------------------------------------------------------


def test_09_active_presentation_resumes_at_the_saved_page(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    first = start(client, headers_a, bdd_course)
    go_to(client, headers_a, bdd_course, numeroPage=6)

    reopened = start(client, headers_a, bdd_course)

    assert reopened["idPresentation"] == first["idPresentation"]
    assert reopened["element"]["numeroPage"] == 6
    assert reopened["positionCourante"] == 7
    assert reopened["etat"] == "EN_PRESENTATION"


def test_10_network_cut_marks_the_presentation_interrupted_then_resumes(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    start(client, headers_a, bdd_course)
    go_to(client, headers_a, bdd_course, numeroPage=5)

    interrupted = act(client, headers_a, bdd_course, "/interruption").json()
    assert interrupted["etat"] == "INTERROMPUE"
    assert act(client, headers_a, bdd_course, "/suivant").status_code == 409

    resumed = start(client, headers_a, bdd_course)
    assert resumed["etat"] == "EN_PRESENTATION"
    assert resumed["element"]["numeroPage"] == 5


# --- CA5: frozen version ----------------------------------------------------------------


def test_11_course_version_is_frozen_for_the_whole_presentation(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    db: sqlite3.Connection,
) -> None:
    assert start(client, headers_a, bdd_course)["version"] == 1
    # Simulates another story publishing version 2 while the session is running.
    db.execute("UPDATE course_versions SET is_active = 0 WHERE course_id = ?", (bdd_course["id"],))
    db.execute(
        "INSERT INTO course_versions"
        " (course_id, version_number, page_count, is_active, page_fingerprints, created_at)"
        " VALUES (?, 2, 12, 1, ?, ?)",
        (bdd_course["id"], json.dumps(["f"] * 12), "2026-11-25T10:00:00+00:00"),
    )

    body = start(client, headers_a, bdd_course)

    assert body["version"] == 1
    assert body["nbElements"] == 12
    pages = [element for element in body["elements"] if element["type"] == "PAGE"]
    assert all("/versions/1/" in element["pageUrl"] for element in pages)


# --- CA6: termination -------------------------------------------------------------------


def test_12_finishing_closes_the_presentation_and_the_next_one_starts_at_page_one(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    db: sqlite3.Connection,
) -> None:
    first = start(client, headers_a, bdd_course)
    go_to(client, headers_a, bdd_course, numeroPage=3)

    finished = act(client, headers_a, bdd_course, "/terminer")
    assert finished.status_code == 200
    assert finished.json()["etat"] == "TERMINEE"

    second = start(client, headers_a, bdd_course)
    assert second["idPresentation"] != first["idPresentation"]
    assert second["positionCourante"] == 1
    row = db.execute(
        "SELECT state, ended_at FROM presentations WHERE id = ?", (first["idPresentation"],)
    ).fetchone()
    assert row["state"] == "TERMINEE"
    assert row["ended_at"] is not None


def test_13_finishing_releases_the_version_lock(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    start(client, headers_a, bdd_course)
    act(client, headers_a, bdd_course, "/terminer")

    repo = CourseRepository(db)
    previous = repo.get_active_version(bdd_course["id"])
    assert previous is not None
    storage = PdfStorage(settings.storage_dir)
    pdf = make_pdf_bytes(12)
    info = storage.inspect(pdf)
    v2 = repo.create_next_version(bdd_course["id"], previous, info.page_count, info.fingerprints)
    storage.save(bdd_course["id"], v2.version_number, pdf)

    restarted = start(client, headers_a, bdd_course)
    assert restarted["version"] == 2
    assert restarted["positionCourante"] == 1


def test_plan_reflects_qm13_page_zero_and_multiple_quizzes_order(
    client: TestClient,
    headers_a: dict[str, str],
    seed_course,
    seed_uninserted_quiz,
) -> None:
    course, version = seed_course("prof_a", "Déroulé QM-13", 3)
    q_zero = seed_uninserted_quiz(course.id, "Intro", 1)
    q_first = seed_uninserted_quiz(course.id, "Milieu A", 1)
    q_second = seed_uninserted_quiz(course.id, "Milieu B", 1)
    for quiz_id, page in ((q_zero, 0), (q_first, 2), (q_second, 2)):
        res = client.post(
            f"/api/cours/{course.id}/versions/{version.id}/insertions",
            headers=headers_a,
            json={"idQuiz": quiz_id, "apresPage": page},
        )
        assert res.status_code == 201

    plan = client.get(f"/cours/{course.id}/presentation", headers=headers_a).json()
    summary = [
        (el["type"], el["numeroPage"] if el["type"] == "PAGE" else el["idQuiz"])
        for el in plan["elements"]
    ]
    assert summary == [
        ("QUIZ", q_zero),
        ("PAGE", 1),
        ("PAGE", 2),
        ("QUIZ", q_first),
        ("QUIZ", q_second),
        ("PAGE", 3),
    ]


def test_terminating_without_a_presentation_returns_404(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    response = act(client, headers_a, bdd_course, "/terminer")
    assert response.status_code == 404
    assert response.json()["erreur"] == "PRESENTATION_INTROUVABLE"


# --- CA7: refusals ----------------------------------------------------------------------

ROUTES = [
    ("GET", ""),
    ("POST", "/suivant"),
    ("POST", "/precedent"),
    ("PUT", "/position"),
    ("POST", "/quiz/lancer"),
    ("POST", "/quiz/cloturer"),
    ("POST", "/interruption"),
    ("POST", "/terminer"),
]


@pytest.mark.parametrize(("method", "suffix"), ROUTES)
def test_14_requests_without_session_get_401(
    client: TestClient, bdd_course: dict[str, int], method: str, suffix: str
) -> None:
    response = client.request(method, url(bdd_course["id"], suffix), json={"position": 1})
    assert response.status_code == 401
    assert response.json()["erreur"] == "NON_AUTHENTIFIE"


@pytest.mark.parametrize(("method", "suffix"), ROUTES)
def test_15_other_teacher_gets_403_and_changes_nothing(
    client: TestClient,
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    bdd_course: dict[str, int],
    method: str,
    suffix: str,
) -> None:
    start(client, headers_a, bdd_course)
    response = client.request(
        method, url(bdd_course["id"], suffix), headers=headers_b, json={"position": 5}
    )
    assert response.status_code == 403
    assert response.json()["erreur"] == "ACCES_REFUSE"
    assert start(client, headers_a, bdd_course)["positionCourante"] == 1


def test_16_unknown_course_returns_404(client: TestClient, headers_a: dict[str, str]) -> None:
    response = client.get(url(999999), headers=headers_a)
    assert response.status_code == 404
    assert response.json()["erreur"] == "COURS_INTROUVABLE"


@pytest.mark.parametrize(("method", "suffix"), ROUTES[1:7])
def test_actions_without_a_presentation_return_404(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    method: str,
    suffix: str,
) -> None:
    response = client.request(
        method, url(bdd_course["id"], suffix), headers=headers_a, json={"position": 1}
    )
    assert response.status_code == 404
    assert response.json()["erreur"] == "PRESENTATION_INTROUVABLE"


def test_17_archived_course_cannot_be_presented(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    db: sqlite3.Connection,
) -> None:
    CourseRepository(db).set_course_archived(bdd_course["id"], True)

    response = client.get(url(bdd_course["id"]), headers=headers_a)

    assert response.status_code == 409
    assert response.json()["erreur"] == "COURS_ARCHIVE"
    assert db.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 0


def test_18_missing_pdf_file_refuses_the_presentation(
    client: TestClient,
    headers_a: dict[str, str],
    bdd_course: dict[str, int],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    (settings.storage_dir / str(bdd_course["id"]) / "v1.pdf").unlink()

    response = client.get(url(bdd_course["id"]), headers=headers_a)

    assert response.status_code == 409
    assert response.json()["erreur"] == "PDF_INDISPONIBLE"
    assert db.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 0


def test_httponly_cookie_is_accepted_by_the_presentation_routes(
    client: TestClient, token_factory, bdd_course: dict[str, int]
) -> None:
    headers = {"Cookie": f"access_token={token_factory()}"}
    assert client.get(url(bdd_course["id"]), headers=headers).status_code == 200


# --- Page access (tests 19 and 20) ------------------------------------------------------


def test_20_page_is_served_as_a_single_page_pdf_to_its_owner(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    response = client.get(f"/cours/{bdd_course['id']}/versions/1/pages/2", headers=headers_a)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"].startswith("private")
    assert read_single_page_width(response.content) == 201.0

    api_alias = client.get(page_url(bdd_course, 2), headers=headers_a)
    assert api_alias.status_code == 200
    assert api_alias.content == response.content


def test_20_other_teacher_and_anonymous_cannot_read_pages(
    client: TestClient, headers_b: dict[str, str], bdd_course: dict[str, int]
) -> None:
    path = f"/cours/{bdd_course['id']}/versions/1/pages/1"
    forbidden = client.get(path, headers=headers_b)
    anonymous = client.get(path)
    assert forbidden.status_code == 403
    assert anonymous.status_code == 401
    assert b"%PDF" not in forbidden.content


def test_unknown_version_or_page_returns_404(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int]
) -> None:
    base = f"/cours/{bdd_course['id']}/versions"
    missing_version = client.get(f"{base}/9/pages/1", headers=headers_a)
    missing_page = client.get(f"{base}/1/pages/11", headers=headers_a)
    page_zero = client.get(f"{base}/1/pages/0", headers=headers_a)
    assert (missing_version.status_code, missing_version.json()["erreur"]) == (
        404,
        "VERSION_INTROUVABLE",
    )
    assert (missing_page.status_code, missing_page.json()["erreur"]) == (404, "PAGE_INTROUVABLE")
    assert page_zero.status_code == 404


def test_page_of_a_missing_file_returns_409(
    client: TestClient, headers_a: dict[str, str], bdd_course: dict[str, int], settings: Settings
) -> None:
    (settings.storage_dir / str(bdd_course["id"]) / "v1.pdf").unlink()
    response = client.get(f"/cours/{bdd_course['id']}/versions/1/pages/1", headers=headers_a)
    assert response.status_code == 409
    assert response.json()["erreur"] == "PDF_INDISPONIBLE"
