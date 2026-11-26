"""Tests de recette QM-11 (docs/specs/QM-11.md) : importer un cours PDF."""

import io
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit

from app.config import Settings
from app.main import create_app
from app.repositories.cours import DepotIndisponible, InMemoryCoursRepository, get_cours_repository
from app.services import cours as service_cours

AUTH_A = {"Authorization": "Bearer enseignantA"}
AUTH_B = {"Authorization": "Bearer enseignantB"}
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- Fixtures -----------------------------------------------------------------------------


@pytest.fixture
def repo() -> InMemoryCoursRepository:
    return InMemoryCoursRepository()


@pytest.fixture
def stockage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dossier = tmp_path / "pdf"
    monkeypatch.setenv("STORAGE_DIR", str(dossier))
    return dossier


@pytest.fixture
def client(
    settings: Settings,
    repo: InMemoryCoursRepository,
    stockage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.delenv("QUIZMO_UTILISATEUR_DEV", raising=False)
    application = create_app(settings)
    application.dependency_overrides[get_cours_repository] = lambda: repo
    with TestClient(application) as test_client:
        yield test_client


# --- Fichiers de test ---------------------------------------------------------------------


def en_octets(redacteur: PdfWriter) -> bytes:
    tampon = io.BytesIO()
    redacteur.write(tampon)
    return tampon.getvalue()


def faire_pdf(nb_pages: int = 10) -> bytes:
    redacteur = PdfWriter()
    for i in range(nb_pages):
        redacteur.add_blank_page(width=200 + i, height=200)
    return en_octets(redacteur)


def faire_pdf_chiffre(algorithme: str, mot_de_passe: str = "secret") -> bytes:
    redacteur = PdfWriter()
    redacteur.add_blank_page(width=200, height=200)
    redacteur.encrypt(mot_de_passe, owner_password="proprio", algorithm=algorithme)
    return en_octets(redacteur)


def faire_png() -> bytes:
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
    titre: str | None = "Bases de données",
    nom: str = "cours.pdf",
    mime: str = "application/pdf",
    headers: dict[str, str] | None = AUTH_A,
) -> Response:
    return client.post(
        "/api/cours",
        data={} if titre is None else {"titre": titre},
        files={"fichier": (nom, contenu, mime)},
        headers=headers,
    )


def verifier_erreur(reponse: Response, statut: int, code: str) -> str:
    assert reponse.status_code == statut
    corps = reponse.json()
    assert set(corps) == {"code", "message"}
    assert corps["code"] == code
    assert corps["message"]
    return corps["message"]


def verifier_rien_cree(repo: InMemoryCoursRepository, stockage: Path) -> None:
    assert repo.lister("enseignantA") == []
    assert repo.lister("enseignantB") == []
    assert not stockage.exists() or list(stockage.iterdir()) == []


# --- Tests de recette ---------------------------------------------------------------------


def test_t01_pdf_valide_10_pages(client: TestClient) -> None:
    reponse = importer(client, faire_pdf(10))

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps == {"idCours": 1, "idVersion": 1, "nbPages": 10}

    liste = client.get("/api/cours", headers=AUTH_A)
    assert liste.status_code == 200
    assert liste.json() == [
        {"idCours": 1, "titre": "Bases de données", "version": 1, "nbPages": 10, "nbQuiz": 0}
    ]


def test_t02_donnees_enregistrees(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    pdf = faire_pdf(10)
    assert importer(client, pdf).status_code == 201

    [cours] = repo.lister("enseignantA")
    assert cours.titre == "Bases de données"
    assert cours.proprietaire == "enseignantA"
    [version] = cours.versions
    assert version.numero == 1
    assert version.courante is True
    assert version.nb_pages == 10
    assert len(version.empreintes) == 10
    assert len(set(version.empreintes)) == 10  # les 10 pages sont différentes
    assert all(len(bytes.fromhex(e)) == 32 for e in version.empreintes)  # SHA-256

    fichiers = [f for f in stockage.rglob("*") if f.is_file()]
    assert fichiers == [stockage / str(cours.id_cours) / "v1.pdf"]
    assert fichiers[0].stat().st_size == len(pdf)
    assert fichiers[0].read_bytes() == pdf


def test_t03_fichier_49_mo(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert service_cours.TAILLE_MAX_OCTETS == 50 * 1024 * 1024
    pdf = faire_pdf(10)
    # Limite abaissée : le fichier pèse 49/50 de la limite.
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf) * 50 // 49)

    assert importer(client, pdf).status_code == 201


def test_t03_fichier_exactement_a_la_limite(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = faire_pdf(10)
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf))

    assert importer(client, pdf).status_code == 201


@pytest.mark.parametrize("titre", ["", None])
def test_t04_titre_manquant(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path, titre: str | None
) -> None:
    reponse = importer(client, faire_pdf(), titre=titre)

    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(repo, stockage)


def test_t05_titre_trois_espaces(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    reponse = importer(client, faire_pdf(), titre="   ")

    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(repo, stockage)


def test_t06_fichier_51_mo(
    client: TestClient,
    repo: InMemoryCoursRepository,
    stockage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = faire_pdf(10)
    # Limite abaissée : le fichier pèse 51/50 de la limite.
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(pdf) * 50 // 51)

    message = verifier_erreur(importer(client, pdf), 413, "FICHIER_TROP_VOLUMINEUX")

    assert "compress" in message and "découp" in message
    verifier_rien_cree(repo, stockage)


@pytest.mark.parametrize("contenu", [b"PK\x03\x04 contenu docx", faire_pdf(1)])
def test_t07_docx(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path, contenu: bytes
) -> None:
    # Le second cas a une signature PDF : le type MIME seul doit suffire au refus.
    reponse = importer(client, contenu, nom="cours.docx", mime=MIME_DOCX)

    verifier_erreur(reponse, 415, "FORMAT_NON_PDF")
    verifier_rien_cree(repo, stockage)


def test_t08_png_renomme_en_pdf(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    reponse = importer(client, faire_png(), nom="image.pdf", mime="application/pdf")

    verifier_erreur(reponse, 415, "FORMAT_NON_PDF")
    verifier_rien_cree(repo, stockage)


@pytest.mark.parametrize("part", [0.1, 0.5, 0.9, 0.98])
def test_t09_pdf_tronque(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path, part: float
) -> None:
    pdf = faire_pdf(10)

    reponse = importer(client, pdf[: int(len(pdf) * part)])

    message = verifier_erreur(reponse, 422, "PDF_ILLISIBLE")
    assert "réexport" in message.lower()
    verifier_rien_cree(repo, stockage)


def test_t09_pdf_a_plusieurs_revisions_tronque(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    # Un PDF enregistré en plusieurs fois contient déjà un %%EOF avant la coupure.
    pdf = faire_pdf(10) + b"99 0 obj\n<< /Length 9000 >>\nstream\n" + b"A" * 5000

    verifier_erreur(importer(client, pdf), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(repo, stockage)


def test_t09_pdf_abime_au_milieu(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    # La fin du fichier est intacte : pypdf le « répare » en perdant des pages.
    pdf = faire_pdf(10)
    debut, fin = len(pdf) // 5, len(pdf) * 2 // 5
    abime = pdf[:debut] + b"\0" * (fin - debut) + pdf[fin:]

    verifier_erreur(importer(client, abime), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(repo, stockage)


def test_t09_pdf_sans_page(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    verifier_erreur(importer(client, faire_pdf(0)), 422, "PDF_ILLISIBLE")
    verifier_rien_cree(repo, stockage)


@pytest.mark.parametrize("algorithme", ["RC4-128", "AES-128", "AES-256"])
def test_t10_pdf_chiffre(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path, algorithme: str
) -> None:
    reponse = importer(client, faire_pdf_chiffre(algorithme))

    message = verifier_erreur(reponse, 422, "PDF_CHIFFRE")
    assert "non protégé" in message
    verifier_rien_cree(repo, stockage)


def test_t10_pdf_chiffre_sans_mot_de_passe_utilisateur(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    reponse = importer(client, faire_pdf_chiffre("AES-256", mot_de_passe=""))

    verifier_erreur(reponse, 422, "PDF_CHIFFRE")
    verifier_rien_cree(repo, stockage)


class DepotArrete(InMemoryCoursRepository):
    """Dépôt qui tombe en panne sur une opération donnée."""

    def __init__(self, operation: str, stockage: Path) -> None:
        super().__init__()
        self._operation = operation
        self._stockage = stockage
        self.fichier_ecrit_avant_panne = False

    def prochain_id(self) -> int:
        if self._operation == "prochain_id":
            raise DepotIndisponible()
        return super().prochain_id()

    def ajouter(self, *args, **kwargs):
        if self._operation == "ajouter":
            self.fichier_ecrit_avant_panne = (self._stockage / "1" / "v1.pdf").is_file()
            raise DepotIndisponible()
        return super().ajouter(*args, **kwargs)


@pytest.mark.parametrize("operation", ["prochain_id", "ajouter"])
def test_t11_bdd_arretee(client: TestClient, stockage: Path, operation: str) -> None:
    depot = DepotArrete(operation, stockage)
    client.app.dependency_overrides[get_cours_repository] = lambda: depot

    message = verifier_erreur(importer(client, faire_pdf()), 503, "BDD_INDISPONIBLE")

    assert "Réessayez dans quelques minutes ou prévenez l'administrateur" in message
    assert depot.fichier_ecrit_avant_panne is (operation == "ajouter")
    verifier_rien_cree(depot, stockage)


def test_t11_erreur_inattendue_supprime_le_fichier(
    client: TestClient,
    repo: InMemoryCoursRepository,
    stockage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ajouter_en_panne(*args, **kwargs):
        raise RuntimeError("panne")

    monkeypatch.setattr(repo, "ajouter", ajouter_en_panne)

    with pytest.raises(RuntimeError):
        importer(client, faire_pdf())

    verifier_rien_cree(repo, stockage)


def test_t11_disque_indisponible(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    stockage.write_text("un fichier à la place du dossier de stockage")

    verifier_erreur(importer(client, faire_pdf()), 503, "BDD_INDISPONIBLE")

    assert repo.lister("enseignantA") == []


def test_t12_correction_apres_erreur(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    pdf = faire_pdf(10)
    verifier_erreur(importer(client, pdf, titre=""), 400, "TITRE_MANQUANT")
    verifier_rien_cree(repo, stockage)

    assert importer(client, pdf, titre="Réseaux").status_code == 201

    [cours] = repo.lister("enseignantA")
    assert cours.titre == "Réseaux"
    assert len([f for f in stockage.rglob("*") if f.is_file()]) == 1


@pytest.mark.parametrize(
    "headers", [None, {"Authorization": "Bearer inconnu"}, {"Authorization": "enseignantA"}]
)
def test_t13_sans_session(
    client: TestClient,
    repo: InMemoryCoursRepository,
    stockage: Path,
    headers: dict[str, str] | None,
) -> None:
    reponse = importer(client, faire_pdf(), headers=headers)

    verifier_erreur(reponse, 401, "NON_AUTHENTIFIE")
    verifier_rien_cree(repo, stockage)


def test_t13_liste_sans_session(client: TestClient) -> None:
    verifier_erreur(client.get("/api/cours"), 401, "NON_AUTHENTIFIE")


# --- Compléments : ordre des contrôles, format d'erreur, auth de dev, cloisonnement -------


def test_ordre_des_controles(
    client: TestClient,
    repo: InMemoryCoursRepository,
    stockage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un envoi qui cumule toutes les fautes : on les corrige une par une, dans l'ordre."""
    png = faire_png()
    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", len(png) - 1)

    verifier_erreur(importer(client, png, titre=" ", headers=None), 401, "NON_AUTHENTIFIE")
    verifier_erreur(importer(client, png, titre=" "), 400, "TITRE_MANQUANT")
    verifier_erreur(importer(client, png), 413, "FICHIER_TROP_VOLUMINEUX")

    monkeypatch.setattr(service_cours, "TAILLE_MAX_OCTETS", 1_000_000)
    verifier_erreur(importer(client, png), 415, "FORMAT_NON_PDF")

    depot = DepotArrete("prochain_id", stockage)
    client.app.dependency_overrides[get_cours_repository] = lambda: depot
    verifier_erreur(importer(client, b"%PDF-1.7\nabime"), 422, "PDF_ILLISIBLE")
    verifier_erreur(importer(client, faire_pdf_chiffre("AES-256")), 422, "PDF_CHIFFRE")
    verifier_erreur(importer(client, faire_pdf()), 503, "BDD_INDISPONIBLE")
    verifier_rien_cree(depot, stockage)


def test_fichier_manquant(
    client: TestClient, repo: InMemoryCoursRepository, stockage: Path
) -> None:
    reponse = client.post("/api/cours", data={"titre": "Réseaux"}, headers=AUTH_A)
    verifier_erreur(reponse, 400, "FICHIER_MANQUANT")

    reponse = client.post("/api/cours", data={"titre": ""}, headers=AUTH_A)
    verifier_erreur(reponse, 400, "TITRE_MANQUANT")
    verifier_rien_cree(repo, stockage)


def test_erreurs_fastapi_au_format_de_l_equipe(client: TestClient) -> None:
    reponse = client.post(
        "/api/cours", data={"titre": "Réseaux", "fichier": "du texte"}, headers=AUTH_A
    )
    assert reponse.status_code == 400
    assert reponse.json()["erreur"] == "VALIDATION"

    reponse = client.get("/api/inexistant")
    assert reponse.status_code == 404
    assert {"erreur", "message"} <= set(reponse.json())


def test_pdf_avec_liens_entre_pages(client: TestClient) -> None:
    redacteur = PdfWriter()
    for _ in range(200):
        redacteur.add_blank_page(width=200, height=200)
    for i in range(200):
        for j in range(10):
            lien = Link(
                rect=(0, 0, 10, 10), target_page_index=(i * 7 + j * 13) % 200, fit=Fit.fit()
            )
            redacteur.add_annotation(i, lien)

    reponse = importer(client, en_octets(redacteur))

    assert reponse.status_code == 201
    assert reponse.json()["nbPages"] == 200


def test_utilisateur_dev_sans_en_tete(
    client: TestClient, repo: InMemoryCoursRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUIZMO_UTILISATEUR_DEV", "enseignantA")

    assert importer(client, faire_pdf(), headers=None).status_code == 201
    assert len(repo.lister("enseignantA")) == 1


def test_liste_limitee_a_l_enseignant_connecte(client: TestClient) -> None:
    assert importer(client, faire_pdf(), headers=AUTH_B).status_code == 201

    assert client.get("/api/cours", headers=AUTH_A).json() == []
    assert len(client.get("/api/cours", headers=AUTH_B).json()) == 1
