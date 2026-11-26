"""Tests de recette QM-11 (docs/specs/QM-11.md) : importer un cours PDF."""

import io
import sqlite3
import struct
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit

from app.config import Settings
from app.courses.pdf_storage import PdfStorage
from app.courses.repository import CourseRepository
from app.database import transaction
from app.main import create_app
from app.services import cours as service_cours
from tests.conftest import TEACHER_A, TEACHER_B
from tests.helpers import valid_quiz_payload

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- Fichiers de test ---------------------------------------------------------------------


def en_octets(redacteur: PdfWriter) -> bytes:
    """Sérialise un PDF en mémoire."""
    tampon = io.BytesIO()
    redacteur.write(tampon)
    return tampon.getvalue()


def faire_pdf(nb_pages: int = 10) -> bytes:
    """PDF valide ; chaque page a une largeur différente, donc une empreinte différente."""
    redacteur = PdfWriter()
    for i in range(nb_pages):
        redacteur.add_blank_page(width=200 + i, height=200)
    return en_octets(redacteur)


def faire_pdf_chiffre(algorithme: str, mot_de_passe: str = "secret") -> bytes:
    """PDF d'une page protégé par mot de passe."""
    redacteur = PdfWriter()
    redacteur.add_blank_page(width=200, height=200)
    redacteur.encrypt(mot_de_passe, owner_password="proprio", algorithm=algorithme)
    return en_octets(redacteur)


def faire_png() -> bytes:
    """Vraie image PNG de 1 pixel."""
    def bloc(nom: bytes, donnees: bytes) -> bytes:
        corps = nom + donnees
        return struct.pack(">I", len(donnees)) + corps + struct.pack(">I", zlib.crc32(corps))

    entete = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", entete) + bloc(b"IDAT", pixels) + bloc(b"IEND", b"")
    )


# --- Aides --------------------------------------------------------------------------------


def importer(
    client: TestClient,
    contenu: bytes,
    headers: dict[str, str] | None,
    titre: str | None = "Bases de données",
    nom: str = "cours.pdf",
    mime: str = "application/pdf",
) -> Response:
    """Envoie POST /api/cours."""
    return client.post(
        "/api/cours",
        data={} if titre is None else {"titre": titre},
        files={"fichier": (nom, contenu, mime)},
        headers=headers,
    )


def verifier_erreur(reponse: Response, statut: int, code: str) -> str:
    """Vérifie statut, code et format d'erreur ; renvoie le message."""
    assert reponse.status_code == statut, reponse.text
    corps = reponse.json()
    assert corps["erreur"] == code
    assert set(corps) <= {"erreur", "message", "action"}
    assert corps["message"]
    return str(corps["message"])


def compter(db: sqlite3.Connection, table: str) -> int:
    """Nombre de lignes d'une table."""
    return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def fichiers_stockes(settings: Settings) -> list[Path]:
    """Fichiers présents dans le stockage des PDF."""
    racine = settings.storage_dir
    return sorted(f for f in racine.rglob("*") if f.is_file()) if racine.exists() else []


def verifier_rien_cree(db: sqlite3.Connection, settings: Settings) -> None:
    """Ni cours, ni version, ni fichier."""
    assert compter(db, "courses") == 0
    assert compter(db, "course_versions") == 0
    racine = settings.storage_dir
    assert not racine.exists() or not list(racine.iterdir())


def panne_sqlite(*_args: object, **_kwargs: object) -> None:
    """Simule une base indisponible."""
    raise sqlite3.OperationalError("database is locked")


# --- Tests de recette ---------------------------------------------------------------------


def test_t01_pdf_valide_10_pages(client: TestClient, headers_a: dict[str, str]) -> None:
    reponse = importer(client, faire_pdf(10), headers_a)

    assert reponse.status_code == 201
    assert reponse.json() == {"idCours": 1, "idVersion": 1, "nbPages": 10}

    liste = client.get("/api/cours", headers=headers_a)
    assert liste.status_code == 200
    assert liste.json() == [
        {"idCours": 1, "titre": "Bases de données", "version": 1, "nbPages": 10, "nbQuiz": 0}
    ]


def test_t02_donnees_enregistrees(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    pdf = faire_pdf(10)
    assert importer(client, pdf, headers_a).status_code == 201

    [cours] = db.execute("SELECT id, title, owner_ldap FROM courses").fetchall()
    assert (cours["title"], cours["owner_ldap"]) == ("Bases de données", TEACHER_A)
    depot = CourseRepository(db)
    version = depot.get_active_version(cours["id"])
    assert version is not None
    assert compter(db, "course_versions") == 1
    assert version.version_number == 1
    assert version.page_count == 10
    assert len(set(version.page_fingerprints)) == 10  # les 10 pages sont différentes
    assert all(len(bytes.fromhex(e)) == 32 for e in version.page_fingerprints)  # SHA-256

    assert fichiers_stockes(settings) == [settings.storage_dir / str(cours["id"]) / "v1.pdf"]
    assert fichiers_stockes(settings)[0].read_bytes() == pdf


def test_t03_fichier_49_mo(
    client: TestClient, headers_a: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert service_cours.TAILLE_MAX_OCTETS == 50 * 1024 * 1024
    pdf = faire_pdf(10)
    # Limite abaissée : le fichier pèse 49/50 de la limite.
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf) * 50 // 49)

    assert importer(client, pdf, headers_a).status_code == 201


def test_t03_fichier_exactement_a_la_limite(
    client: TestClient, headers_a: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = faire_pdf(10)
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf))

    assert importer(client, pdf, headers_a).status_code == 201


@pytest.mark.parametrize("titre", ["", None])
def test_t04_titre_manquant(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    titre: str | None,
) -> None:
    reponse = importer(client, faire_pdf(), headers_a, titre=titre)

    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(db, settings)


def test_t05_titre_trois_espaces(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    reponse = importer(client, faire_pdf(), headers_a, titre="   ")

    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(db, settings)


def test_t06_fichier_51_mo(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = faire_pdf(10)
    # Limite abaissée : le fichier pèse 51/50 de la limite.
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf) * 50 // 51)

    message = verifier_erreur(importer(client, pdf, headers_a), 413, "FICHIER_TROP_VOLUMINEUX")

    assert "compress" in message and "découp" in message
    verifier_rien_cree(db, settings)


@pytest.mark.parametrize("contenu", [b"PK\x03\x04 contenu docx", faire_pdf(1)])
def test_t07_docx(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    contenu: bytes,
) -> None:
    # Le second cas a une signature PDF : le type MIME seul doit suffire au refus.
    reponse = importer(client, contenu, headers_a, nom="cours.docx", mime=MIME_DOCX)

    verifier_erreur(reponse, 415, "FORMAT_NON_PDF")
    verifier_rien_cree(db, settings)


def test_t08_png_renomme_en_pdf(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    reponse = importer(client, faire_png(), headers_a, nom="image.pdf")

    verifier_erreur(reponse, 415, "FORMAT_NON_PDF")
    verifier_rien_cree(db, settings)


@pytest.mark.parametrize("part", [0.1, 0.5, 0.9, 0.98])
def test_t09_pdf_tronque(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    part: float,
) -> None:
    pdf = faire_pdf(10)

    reponse = importer(client, pdf[: int(len(pdf) * part)], headers_a)

    message = verifier_erreur(reponse, 422, "PDF_ILLISIBLE")
    assert "réexport" in message.lower()
    verifier_rien_cree(db, settings)


def test_t09_pdf_a_plusieurs_revisions_tronque(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    # Un PDF enregistré en plusieurs fois contient déjà un %%EOF avant la coupure.
    pdf = faire_pdf(10) + b"99 0 obj\n<< /Length 9000 >>\nstream\n" + b"A" * 5000

    verifier_erreur(importer(client, pdf, headers_a), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(db, settings)


def test_t09_pdf_abime_au_milieu(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    # La fin du fichier est intacte : pypdf le « répare » en perdant des pages.
    pdf = faire_pdf(10)
    debut, fin = len(pdf) // 5, len(pdf) * 2 // 5
    abime = pdf[:debut] + b"\0" * (fin - debut) + pdf[fin:]

    verifier_erreur(importer(client, abime, headers_a), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(db, settings)


def test_t09_pdf_sans_page(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    verifier_erreur(importer(client, faire_pdf(0), headers_a), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(db, settings)


@pytest.mark.parametrize("algorithme", ["RC4-128", "AES-128", "AES-256"])
def test_t10_pdf_chiffre(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    algorithme: str,
) -> None:
    reponse = importer(client, faire_pdf_chiffre(algorithme), headers_a)

    message = verifier_erreur(reponse, 422, "PDF_CHIFFRE")
    assert "non protégé" in message
    verifier_rien_cree(db, settings)


def test_t10_pdf_chiffre_sans_mot_de_passe_utilisateur(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    reponse = importer(client, faire_pdf_chiffre("AES-256", mot_de_passe=""), headers_a)

    verifier_erreur(reponse, 422, "PDF_CHIFFRE")
    verifier_rien_cree(db, settings)


def test_t11_bdd_injoignable(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.dependencies.connect", panne_sqlite)

    message = verifier_erreur(importer(client, faire_pdf(), headers_a), 503, "BDD_INDISPONIBLE")

    assert "Réessayez dans quelques minutes ou prévenez l'administrateur" in message
    verifier_rien_cree(db, settings)


def test_t11_bdd_en_panne_a_l_enregistrement(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CourseRepository, "create_course_with_v1", panne_sqlite)

    verifier_erreur(importer(client, faire_pdf(), headers_a), 503, "BDD_INDISPONIBLE")
    verifier_rien_cree(db, settings)


def test_t11_bdd_en_panne_apres_ecriture_du_fichier(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fichier_ecrit = []

    @contextmanager
    def commit_en_echec(connexion: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        with transaction(connexion):
            yield connexion
            fichier_ecrit.extend(fichiers_stockes(settings))
            raise sqlite3.OperationalError("disk I/O error")  # le COMMIT échoue

    monkeypatch.setattr(service_cours, "transaction", commit_en_echec)

    verifier_erreur(importer(client, faire_pdf(), headers_a), 503, "BDD_INDISPONIBLE")

    assert fichier_ecrit == [settings.storage_dir / "1" / "v1.pdf"]
    verifier_rien_cree(db, settings)


def test_t11_erreur_inattendue_supprime_le_fichier(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enregistrer = PdfStorage.save

    def enregistrer_puis_planter(self: PdfStorage, *args: object) -> None:
        enregistrer(self, *args)  # type: ignore[arg-type]
        raise RuntimeError("panne")

    monkeypatch.setattr(PdfStorage, "save", enregistrer_puis_planter)

    with pytest.raises(RuntimeError):
        importer(client, faire_pdf(), headers_a)

    verifier_rien_cree(db, settings)


def test_t11_disque_indisponible(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    settings.storage_dir.write_text("un fichier à la place du dossier de stockage")

    verifier_erreur(importer(client, faire_pdf(), headers_a), 503, "BDD_INDISPONIBLE")

    assert compter(db, "courses") == 0
    assert compter(db, "course_versions") == 0


def test_t12_correction_apres_erreur(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    pdf = faire_pdf(10)
    verifier_erreur(importer(client, pdf, headers_a, titre=""), 400, "TITRE_MANQUANT")
    verifier_rien_cree(db, settings)

    assert importer(client, pdf, headers_a, titre="Réseaux").status_code == 201

    assert [r["title"] for r in db.execute("SELECT title FROM courses")] == ["Réseaux"]
    assert len(fichiers_stockes(settings)) == 1


@pytest.mark.parametrize(
    "headers", [None, {"Authorization": "Bearer inconnu"}, {"Authorization": "prof_a"}]
)
def test_t13_sans_session(
    client: TestClient,
    db: sqlite3.Connection,
    settings: Settings,
    headers: dict[str, str] | None,
) -> None:
    reponse = importer(client, faire_pdf(), headers)

    verifier_erreur(reponse, 401, "NON_AUTHENTIFIE")
    verifier_rien_cree(db, settings)


def test_t13_liste_sans_session(client: TestClient) -> None:
    verifier_erreur(client.get("/api/cours"), 401, "NON_AUTHENTIFIE")


# --- Compléments : ordre des contrôles, format d'erreur, auth de dev, intégration ---------


def test_ordre_des_controles(
    client: TestClient,
    headers_a: dict[str, str],
    db: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un envoi qui cumule toutes les fautes : on les corrige une par une, dans l'ordre."""
    png = faire_png()
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(png) - 1)

    verifier_erreur(importer(client, png, None, titre=" "), 401, "NON_AUTHENTIFIE")
    verifier_erreur(importer(client, png, headers_a, titre=" "), 400, "TITRE_MANQUANT")
    verifier_erreur(importer(client, png, headers_a), 413, "FICHIER_TROP_VOLUMINEUX")

    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", 1_000_000)
    verifier_erreur(importer(client, png, headers_a), 415, "FORMAT_NON_PDF")

    monkeypatch.setattr(CourseRepository, "create_course_with_v1", panne_sqlite)
    verifier_erreur(importer(client, b"%PDF-1.7\nabime", headers_a), 422, "PDF_ILLISIBLE")
    verifier_erreur(importer(client, faire_pdf_chiffre("AES-256"), headers_a), 422, "PDF_CHIFFRE")
    verifier_erreur(importer(client, faire_pdf(), headers_a), 503, "BDD_INDISPONIBLE")
    verifier_rien_cree(db, settings)


def test_fichier_manquant(
    client: TestClient, headers_a: dict[str, str], db: sqlite3.Connection, settings: Settings
) -> None:
    reponse = client.post("/api/cours", data={"titre": "Réseaux"}, headers=headers_a)
    verifier_erreur(reponse, 400, "FICHIER_MANQUANT")

    reponse = client.post("/api/cours", data={"titre": ""}, headers=headers_a)
    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(db, settings)


def test_erreurs_fastapi_au_format_de_l_equipe(
    client: TestClient, headers_a: dict[str, str]
) -> None:
    reponse = client.post(
        "/api/cours", data={"titre": "Réseaux", "fichier": "du texte"}, headers=headers_a
    )
    assert reponse.status_code == 400
    assert reponse.json()["erreur"] == "VALIDATION"

    reponse = client.get("/api/inexistant")
    assert reponse.status_code == 404
    assert {"erreur", "message"} <= set(reponse.json())


def test_pdf_avec_liens_entre_pages(client: TestClient, headers_a: dict[str, str]) -> None:
    redacteur = PdfWriter()
    for _ in range(200):
        redacteur.add_blank_page(width=200, height=200)
    for i in range(200):
        for j in range(10):
            lien = Link(
                rect=(0, 0, 10, 10), target_page_index=(i * 7 + j * 13) % 200, fit=Fit.fit()
            )
            redacteur.add_annotation(i, lien)

    reponse = importer(client, en_octets(redacteur), headers_a)

    assert reponse.status_code == 201
    assert reponse.json()["nbPages"] == 200


def test_utilisateur_dev_sans_en_tete(
    settings: Settings, db: sqlite3.Connection, headers_b: dict[str, str]
) -> None:
    reglages = settings.model_copy(update={"utilisateur_dev": TEACHER_A})
    with TestClient(create_app(reglages)) as client_dev:
        reponse = importer(client_dev, faire_pdf(), None)
        assert reponse.status_code == 201
        id_cours, id_version = reponse.json()["idCours"], reponse.json()["idVersion"]

        # Les routes de l'équipe acceptent aussi l'enseignant de développement.
        insertions = client_dev.get(f"/api/cours/{id_cours}/versions/{id_version}/insertions")
        assert insertions.status_code == 200
        # Un en-tête présent est toujours vérifié.
        verifier_erreur(
            importer(client_dev, faire_pdf(), {"Authorization": "Bearer faux"}),
            401,
            "NON_AUTHENTIFIE",
        )
        assert importer(client_dev, faire_pdf(), headers_b).status_code == 201

    proprietaires = [r["owner_ldap"] for r in db.execute("SELECT owner_ldap FROM courses")]
    assert proprietaires == [TEACHER_A, TEACHER_B]


def test_liste_limitee_a_l_enseignant_connecte(
    client: TestClient, headers_a: dict[str, str], headers_b: dict[str, str]
) -> None:
    assert importer(client, faire_pdf(), headers_b).status_code == 201

    assert client.get("/api/cours", headers=headers_a).json() == []
    assert len(client.get("/api/cours", headers=headers_b).json()) == 1


def test_cours_importe_utilisable_par_les_quiz_et_les_insertions(
    client: TestClient,
    headers_a: dict[str, str],
    seed_uninserted_quiz: Callable[..., int],
) -> None:
    reponse = importer(client, faire_pdf(10), headers_a)
    assert reponse.status_code == 201
    id_cours, id_version = reponse.json()["idCours"], reponse.json()["idVersion"]

    # QM-12 : création d'un quiz inséré après la page 4.
    quiz = client.post(
        f"/api/cours/{id_cours}/quiz", headers=headers_a, json=valid_quiz_payload(4)
    )
    assert quiz.status_code == 201, quiz.text

    # QM-13 : insertion d'un quiz existant après la page 7.
    id_quiz = seed_uninserted_quiz(id_cours)
    insertion = client.post(
        f"/api/cours/{id_cours}/versions/{id_version}/insertions",
        headers=headers_a,
        json={"idQuiz": id_quiz, "apresPage": 7},
    )
    assert insertion.status_code == 201, insertion.text

    liste = client.get(f"/api/cours/{id_cours}/versions/{id_version}/insertions", headers=headers_a)
    assert [i["apresPage"] for i in liste.json()] == [4, 7]

    # QM-14 : la présentation trouve le PDF au bon endroit du stockage.
    assert client.get(f"/api/cours/{id_cours}/presentation", headers=headers_a).status_code == 200
