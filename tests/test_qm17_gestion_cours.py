"""Tests de recette QM-17 (docs/specs/QM-17.md) : consulter et gérer ses cours."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.courses.records import CourseRecord, VersionRecord
from tests.conftest import TEACHER_A, TEACHER_B

SeedCourse = Callable[..., tuple[CourseRecord, VersionRecord]]


@pytest.fixture
def jeu(
    seed_course: SeedCourse,
    add_quiz: Callable[..., dict[str, Any]],
    add_leaderboard: Callable[..., dict[str, int]],
    headers_a: dict[str, str],
) -> dict[str, int]:
    """Jeu de données de la recette QM-17.

    A possède « Bases de données » (10 p, Q1 après p.4, L1 après p.8, Q2 après p.9) et
    « Réseaux » (5 p, aucun quiz) ; B possède « Algorithmique ».
    """
    bdd, _ = seed_course(TEACHER_A, "Bases de données", 10)
    q1 = add_quiz(headers_a, bdd.id, 4)
    l1 = add_leaderboard(bdd.id, 8, "L1")
    q2 = add_quiz(headers_a, bdd.id, 9)
    reseaux, _ = seed_course(TEACHER_A, "Réseaux", 5)
    algo, _ = seed_course(TEACHER_B, "Algorithmique", 8)
    return {
        "bdd": bdd.id,
        "reseaux": reseaux.id,
        "algo": algo.id,
        "q1": int(q1["idQuiz"]),
        "q2": int(q2["idQuiz"]),
        "l1": l1["idLeaderboard"],
    }


def verifier_erreur(reponse: Any, statut: int, code: str) -> None:
    """Statut et code d'erreur au format de l'équipe."""
    assert reponse.status_code == statut, reponse.text
    assert reponse.json()["erreur"] == code
    assert reponse.json()["message"]


# --- GET /api/cours -----------------------------------------------------------------------


def test_t01_tableau_de_bord(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    reponse = client.get("/api/cours", headers=headers_a)

    assert reponse.status_code == 200
    assert reponse.json() == [
        {"idCours": jeu["bdd"], "titre": "Bases de données", "version": 1, "nbPages": 10,
         "nbQuiz": 2},
        {"idCours": jeu["reseaux"], "titre": "Réseaux", "version": 1, "nbPages": 5, "nbQuiz": 0},
    ]


@pytest.mark.usefixtures("jeu")
def test_t02_cloisonnement(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
) -> None:
    titres_a = [c["titre"] for c in client.get("/api/cours", headers=headers_a).json()]
    titres_b = [c["titre"] for c in client.get("/api/cours", headers=headers_b).json()]

    assert "Algorithmique" not in titres_a
    assert titres_b == ["Algorithmique"]


@pytest.mark.usefixtures("jeu")
def test_t18_liste_sans_jeton(client: TestClient) -> None:
    verifier_erreur(client.get("/api/cours"), 401, "NON_AUTHENTIFIE")


# --- GET /api/cours/{id} ------------------------------------------------------------------


def positions(client: TestClient, id_cours: int, headers: dict[str, str]) -> dict[str, int]:
    """Titre de chaque quiz / leaderboard → page après laquelle il apparaît."""
    reponse = client.get(f"/api/cours/{id_cours}", headers=headers)
    assert reponse.status_code == 200, reponse.text
    return {i["titre"]: i["apresPage"] for i in reponse.json()["insertions"]}


def test_t05_ouvrir_un_cours(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    reponse = client.get(f"/api/cours/{jeu['bdd']}", headers=headers_a)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert {k: corps[k] for k in ("idCours", "titre", "version", "nbPages")} == {
        "idCours": jeu["bdd"],
        "titre": "Bases de données",
        "version": 1,
        "nbPages": 10,
    }
    assert [(i["type"], i["apresPage"]) for i in corps["insertions"]] == [
        ("QUIZ", 4),
        ("LEADERBOARD", 8),
        ("QUIZ", 9),
    ]
    assert [i["idQuiz"] for i in corps["insertions"]] == [jeu["q1"], None, jeu["q2"]]
    assert corps["insertions"][1]["idLeaderboard"] == jeu["l1"]


def test_t17_ouvrir_le_cours_d_un_autre_enseignant(
    client: TestClient, jeu: dict[str, int], headers_b: dict[str, str]
) -> None:
    verifier_erreur(client.get(f"/api/cours/{jeu['bdd']}", headers=headers_b), 403, "ACCES_REFUSE")


def test_t18_ouvrir_sans_jeton(client: TestClient, jeu: dict[str, int]) -> None:
    verifier_erreur(client.get(f"/api/cours/{jeu['bdd']}"), 401, "NON_AUTHENTIFIE")


def test_t22_cours_inexistant(client: TestClient, headers_a: dict[str, str]) -> None:
    verifier_erreur(client.get("/api/cours/999999", headers=headers_a), 404, "COURS_INTROUVABLE")
