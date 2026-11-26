import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.courses.pdf_storage import PdfStorage
from app.courses.records import CourseRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.database import transaction
from app.exceptions import (
    AccessDeniedError,
    CourseNotFoundError,
    DatabaseUnavailableError,
    FileMissingError,
    FileTooLargeError,
    InternalStorageError,
    NotPdfError,
    TitleMissingError,
)
from app.schemas import CoursDetail, CoursResume, InsertionCours
from app.services import pdf

TAILLE_MAX_OCTETS = 50 * 1024 * 1024  # limite encore « à définir » dans le cahier de recette


@contextmanager
def _base_disponible() -> Iterator[None]:
    """Une erreur SQLite pendant une lecture devient un 503 BDD_INDISPONIBLE."""
    try:
        yield
    except sqlite3.Error as erreur:
        raise DatabaseUnavailableError() from erreur


def _cours_de(
    depot: CourseRepository, enseignant: str, id_cours: int
) -> tuple[CourseRecord, VersionRecord]:
    """Contrôles communs à QM-17 : le cours existe (404) et appartient à l'enseignant (403)."""
    cours = depot.get_course(id_cours)
    if cours is None:
        raise CourseNotFoundError()
    if cours.owner_ldap != enseignant:
        raise AccessDeniedError()
    version = depot.get_active_version(id_cours)
    if version is None:
        raise InternalStorageError("Aucune version active pour ce cours")
    return cours, version


def _detail(depot: CourseRepository, cours: CourseRecord, version: VersionRecord) -> CoursDetail:
    return CoursDetail(
        id_cours=cours.id,
        titre=cours.title,
        version=version.version_number,
        id_version=version.id,
        nb_pages=version.page_count,
        insertions=[
            InsertionCours(
                id_insertion=insertion.id,
                type=insertion.item_type,
                id_quiz=insertion.item_id if insertion.item_type == "QUIZ" else None,
                id_leaderboard=insertion.item_id if insertion.item_type == "LEADERBOARD" else None,
                titre=insertion.title,
                apres_page=insertion.after_page,
                ordre=insertion.ordre,
            )
            for insertion in depot.list_insertions_for_version(version.id)
        ],
    )


def controler_fichier(contenu: bytes | None, type_mime: str | None) -> list[str]:
    """Contrôles 3 à 6 de QM-11, dans l'ordre. Renvoie une empreinte par page."""
    if contenu is None:
        raise FileMissingError()
    if len(contenu) > TAILLE_MAX_OCTETS:
        raise FileTooLargeError(
            f"Le fichier dépasse la taille maximale autorisée ({TAILLE_MAX_OCTETS // 1024**2} Mo). "
            "Choisissez un PDF plus léger (compression, découpage)."
        )
    if type_mime != "application/pdf" or not pdf.a_la_signature_pdf(contenu):
        raise NotPdfError()
    return pdf.calculer_empreintes(contenu)


def importer_cours(
    connexion: sqlite3.Connection,
    stockage: PdfStorage,
    proprietaire: str,
    titre: str,
    contenu: bytes | None,
    type_mime: str | None,
) -> tuple[CourseRecord, VersionRecord]:
    """Contrôle puis enregistre un cours et sa version 1 : tout ou rien, en base et sur disque."""
    titre = titre.strip()
    if not titre:
        raise TitleMissingError()
    empreintes = controler_fichier(contenu, type_mime)
    assert contenu is not None

    cours: CourseRecord | None = None
    try:
        with transaction(connexion):
            cours, version = CourseRepository(connexion).create_course_with_v1(
                titre, proprietaire, len(empreintes), empreintes
            )
            stockage.save(cours.id, 1, contenu)
    except BaseException as erreur:
        # La transaction est annulée ; le fichier, lui, doit être retiré à la main.
        if cours is not None:
            stockage.delete(cours.id, 1)
        if isinstance(erreur, (InternalStorageError, sqlite3.Error, OSError)):
            raise DatabaseUnavailableError() from erreur
        raise
    return cours, version


def lister_cours(connexion: sqlite3.Connection, proprietaire: str) -> list[CoursResume]:
    """Tableau de bord : cours de l'enseignant, version active et nombre de quiz."""
    depot = CourseRepository(connexion)
    with _base_disponible():
        return [
            CoursResume(
                id_cours=cours.id,
                titre=cours.title,
                version=version.version_number,
                nb_pages=version.page_count,
                nb_quiz=depot.count_quizzes(cours.id),
            )
            for cours in depot.list_courses_for_owner(proprietaire)
            if (version := depot.get_active_version(cours.id)) is not None
        ]


def consulter_cours(connexion: sqlite3.Connection, enseignant: str, id_cours: int) -> CoursDetail:
    """Un cours de l'enseignant avec sa version courante et ses insertions."""
    depot = CourseRepository(connexion)
    with _base_disponible():
        cours, version = _cours_de(depot, enseignant, id_cours)
        return _detail(depot, cours, version)
