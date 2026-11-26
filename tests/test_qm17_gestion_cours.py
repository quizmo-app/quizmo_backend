"""Tests de recette QM-17 (docs/specs/QM-17.md) : consulter et gérer ses cours."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.courses.records import CourseRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.database import transaction
from app.services import cours as service_cours
from tests.conftest import TEACHER_A, TEACHER_B
from tests.helpers import make_pdf_bytes

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


# --- POST /api/cours/{id}/versions --------------------------------------------------------


def envoyer_version(
    client: TestClient,
    id_cours: int,
    contenu: bytes,
    headers: dict[str, str] | None,
    mime: str = "application/pdf",
) -> Any:
    """Envoie POST /api/cours/{id}/versions."""
    return client.post(
        f"/api/cours/{id_cours}/versions",
        files={"fichier": ("cours.pdf", contenu, mime)},
        headers=headers,
    )


def etat(
    client: TestClient,
    db: sqlite3.Connection,
    settings: Settings,
    id_cours: int,
    headers: dict[str, str],
) -> tuple[Any, ...]:
    """Tout ce qu'une opération refusée ne doit pas changer (headers : ceux du propriétaire)."""
    reponse = client.get(f"/api/cours/{id_cours}", headers=headers)
    tables = {
        table: db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        for table in ("courses", "course_versions", "insertions", "quizzes", "leaderboards")
    }
    fichiers = sorted(str(f) for f in settings.storage_dir.rglob("*"))
    return reponse.json(), {k: [tuple(r) for r in v] for k, v in tables.items()}, fichiers


def demarrer_presentation(client: TestClient, id_cours: int, headers: dict[str, str]) -> None:
    """Le cours passe en séance (QM-14)."""
    assert client.get(f"/api/cours/{id_cours}/presentation", headers=headers).status_code == 200


def test_t06_version_de_12_pages(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(12), headers_a)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["idCours"], corps["version"], corps["nbPages"]) == (jeu["bdd"], 2, 12)
    assert corps["alertes"] == []
    assert [(i["type"], i["apresPage"]) for i in corps["insertions"]] == [
        ("QUIZ", 4),
        ("LEADERBOARD", 8),
        ("QUIZ", 9),
    ]


def test_t07_ancienne_version_archivee(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    v1 = make_pdf_bytes(10)
    (settings.storage_dir / str(jeu["bdd"]) / "v1.pdf").write_bytes(v1)

    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(12), headers_a)

    assert reponse.json()["idCours"] == jeu["bdd"]
    versions = db.execute(
        "SELECT version_number, is_active FROM course_versions WHERE course_id = ?"
        " ORDER BY version_number",
        (jeu["bdd"],),
    ).fetchall()
    assert [tuple(v) for v in versions] == [(1, 0), (2, 1)]
    dossier = settings.storage_dir / str(jeu["bdd"])
    assert sorted(f.name for f in dossier.iterdir()) == ["v1.pdf", "v2.pdf"]
    assert (dossier / "v1.pdf").read_bytes() == v1
    # Les insertions de la v1 restent attachées à la version archivée.
    v1_id = CourseRepository(db).get_version_by_number(jeu["bdd"], 1)
    assert v1_id is not None
    assert len(CourseRepository(db).list_insertions_for_version(v1_id.id)) == 3


def test_t08_version_de_6_pages(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str], db: sqlite3.Connection
) -> None:
    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(6), headers_a)

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert [(i["type"], i["apresPage"]) for i in corps["insertions"]] == [
        ("QUIZ", 4),
        ("LEADERBOARD", 6),
        ("QUIZ", 6),
    ]
    assert [(a["type"], a["apresPageAvant"], a["apresPage"]) for a in corps["alertes"]] == [
        ("LEADERBOARD", 8, 6),
        ("QUIZ", 9, 6),
    ]
    assert [a["idQuiz"] for a in corps["alertes"]] == [None, jeu["q2"]]

    # Empreinte recalculée sur la page cible de la nouvelle version.
    depot = CourseRepository(db)
    version = depot.get_active_version(jeu["bdd"])
    assert version is not None
    for insertion in depot.list_insertions_for_version(version.id):
        assert insertion.page_fingerprint == version.page_fingerprints[insertion.after_page - 1]


def test_insertion_avant_la_premiere_page_conservee(
    client: TestClient,
    seed_course: SeedCourse,
    seed_uninserted_quiz: Callable[..., int],
    headers_a: dict[str, str],
) -> None:
    cours, version = seed_course(TEACHER_A, "Cours", 10)
    id_quiz = seed_uninserted_quiz(cours.id, "Q0")
    insertion = client.post(
        f"/api/cours/{cours.id}/versions/{version.id}/insertions",
        headers=headers_a,
        json={"idQuiz": id_quiz, "apresPage": 0},
    )
    assert insertion.status_code == 201, insertion.text

    reponse = envoyer_version(client, cours.id, make_pdf_bytes(3), headers_a)

    assert reponse.json()["alertes"] == []
    assert positions(client, cours.id, headers_a) == {"Q0": 0}


@pytest.mark.parametrize(
    "cas",
    [
        (b"PK\x03\x04 contenu docx", "application/msword", 415, "FORMAT_NON_PDF"),
        (b"%PDF-1.7\nabime", "application/pdf", 422, "PDF_ILLISIBLE"),
    ],
)
def test_t11_version_docx_ou_illisible(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    cas: tuple[bytes, str, int, str],
) -> None:
    contenu, mime, statut, code = cas
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    verifier_erreur(envoyer_version(client, jeu["bdd"], contenu, headers_a, mime), statut, code)

    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_t12_version_de_51_mo(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = make_pdf_bytes(12)
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf) * 50 // 51)
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    reponse = envoyer_version(client, jeu["bdd"], pdf, headers_a)

    verifier_erreur(reponse, 413, "FICHIER_TROP_VOLUMINEUX")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_version_sans_fichier(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    reponse = client.post(f"/api/cours/{jeu['bdd']}/versions", headers=headers_a)

    verifier_erreur(reponse, 400, "FICHIER_MANQUANT")


def test_version_bdd_en_panne_apres_ecriture_du_fichier(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avant = etat(client, db, settings, jeu["bdd"], headers_a)
    fichiers_pendant = []

    @contextmanager
    def commit_en_echec(connexion: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        with transaction(connexion):
            yield connexion
            fichiers_pendant.extend(sorted(settings.storage_dir.rglob("v2.pdf")))
            raise sqlite3.OperationalError("disk I/O error")  # le COMMIT échoue

    monkeypatch.setattr(service_cours, "transaction", commit_en_echec)

    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(12), headers_a)

    verifier_erreur(reponse, 503, "BDD_INDISPONIBLE")
    assert len(fichiers_pendant) == 1
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_t20_version_pour_le_cours_d_un_autre_enseignant(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(12), headers_b)

    verifier_erreur(reponse, 403, "ACCES_REFUSE")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_t13_version_pendant_une_seance(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    demarrer_presentation(client, jeu["bdd"], headers_a)
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    reponse = envoyer_version(client, jeu["bdd"], make_pdf_bytes(12), headers_a)

    verifier_erreur(reponse, 409, "COURS_VERROUILLE")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_version_sans_jeton_et_cours_inexistant(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    pdf = make_pdf_bytes(12)
    verifier_erreur(envoyer_version(client, jeu["bdd"], pdf, None), 401, "NON_AUTHENTIFIE")
    verifier_erreur(envoyer_version(client, 999999, pdf, headers_a), 404, "COURS_INTROUVABLE")


# --- PUT /api/cours/{id}/structure --------------------------------------------------------


def ids_insertions(client: TestClient, id_cours: int, headers: dict[str, str]) -> list[int]:
    """Identifiants des insertions de la version courante, dans l'ordre du déroulé."""
    reponse = client.get(f"/api/cours/{id_cours}", headers=headers)
    return [i["idInsertion"] for i in reponse.json()["insertions"]]


def structurer(
    client: TestClient, id_cours: int, positions_: list[dict[str, Any]], headers: Any
) -> Any:
    """Envoie PUT /api/cours/{id}/structure."""
    return client.put(f"/api/cours/{id_cours}/structure", json=positions_, headers=headers)


def test_t09_ajuster_la_structure(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    _, id_l1, _ = ids_insertions(client, jeu["bdd"], headers_a)

    reponse = structurer(client, jeu["bdd"], [{"idInsertion": id_l1, "apresPage": 5}], headers_a)

    assert reponse.status_code == 200, reponse.text
    attendu = [("QUIZ", 4), ("LEADERBOARD", 5), ("QUIZ", 9)]
    assert [(i["type"], i["apresPage"]) for i in reponse.json()["insertions"]] == attendu
    relu = client.get(f"/api/cours/{jeu['bdd']}", headers=headers_a).json()
    assert [(i["type"], i["apresPage"]) for i in relu["insertions"]] == attendu


def test_structure_plusieurs_deplacements_et_echange(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str], db: sqlite3.Connection
) -> None:
    id_q1, id_l1, id_q2 = ids_insertions(client, jeu["bdd"], headers_a)

    reponse = structurer(
        client,
        jeu["bdd"],
        [
            {"idInsertion": id_q1, "apresPage": 8},
            {"idInsertion": id_l1, "apresPage": 4},
            {"idInsertion": id_q2, "apresPage": 8},
        ],
        headers_a,
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()["insertions"]
    assert [(i["idInsertion"], i["apresPage"]) for i in corps] == [
        (id_l1, 4),
        (id_q1, 8),
        (id_q2, 8),
    ]
    depot = CourseRepository(db)
    version = depot.get_active_version(jeu["bdd"])
    assert version is not None
    for insertion in depot.list_insertions_for_version(version.id):
        assert insertion.page_fingerprint == version.page_fingerprints[insertion.after_page - 1]


@pytest.mark.parametrize("page", [99, 0, 11, -1])
def test_t10_position_hors_du_cours(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    page: int,
) -> None:
    id_q1, id_l1, _ = ids_insertions(client, jeu["bdd"], headers_a)
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    # Le premier déplacement est valide : il ne doit pas être appliqué non plus.
    reponse = structurer(
        client,
        jeu["bdd"],
        [{"idInsertion": id_q1, "apresPage": 2}, {"idInsertion": id_l1, "apresPage": page}],
        headers_a,
    )

    verifier_erreur(reponse, 422, "POSITION_INVALIDE")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_structure_insertion_d_un_autre_cours_ou_en_double(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    add_quiz: Callable[..., dict[str, Any]],
) -> None:
    id_autre = add_quiz(headers_a, jeu["reseaux"], 2)["insertion"]["idInsertion"]
    id_q1 = ids_insertions(client, jeu["bdd"], headers_a)[0]
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    autre = structurer(client, jeu["bdd"], [{"idInsertion": id_autre, "apresPage": 2}], headers_a)
    double = structurer(
        client,
        jeu["bdd"],
        [{"idInsertion": id_q1, "apresPage": 2}, {"idInsertion": id_q1, "apresPage": 3}],
        headers_a,
    )
    invalide = structurer(client, jeu["bdd"], [{"idInsertion": id_q1}], headers_a)

    verifier_erreur(autre, 404, "RESSOURCE_INTROUVABLE")
    verifier_erreur(double, 422, "POSITION_INVALIDE")
    verifier_erreur(invalide, 400, "VALIDATION")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_t21_structure_du_cours_d_un_autre_enseignant(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    headers_b: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    id_l1 = ids_insertions(client, jeu["bdd"], headers_a)[1]
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    reponse = structurer(client, jeu["bdd"], [{"idInsertion": id_l1, "apresPage": 5}], headers_b)

    verifier_erreur(reponse, 403, "ACCES_REFUSE")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_t13_structure_pendant_une_seance(
    client: TestClient,
    jeu: dict[str, int],
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
) -> None:
    id_l1 = ids_insertions(client, jeu["bdd"], headers_a)[1]
    demarrer_presentation(client, jeu["bdd"], headers_a)
    avant = etat(client, db, settings, jeu["bdd"], headers_a)

    reponse = structurer(client, jeu["bdd"], [{"idInsertion": id_l1, "apresPage": 5}], headers_a)

    verifier_erreur(reponse, 409, "COURS_VERROUILLE")
    assert etat(client, db, settings, jeu["bdd"], headers_a) == avant


def test_structure_sans_jeton_et_cours_inexistant(
    client: TestClient, jeu: dict[str, int], headers_a: dict[str, str]
) -> None:
    corps = [{"idInsertion": 1, "apresPage": 5}]
    verifier_erreur(structurer(client, jeu["bdd"], corps, None), 401, "NON_AUTHENTIFIE")
    verifier_erreur(structurer(client, 999999, corps, headers_a), 404, "COURS_INTROUVABLE")
