import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.courses.pdf_storage import PdfStorage
from app.courses.records import CourseRecord, VersionRecord
from app.courses.repository import CourseRepository
from app.database import transaction
from app.exceptions import (
    AccessDeniedError,
    CourseLockedError,
    CourseNotFoundError,
    DatabaseUnavailableError,
    FileMissingError,
    FileTooLargeError,
    InternalStorageError,
    InvalidPositionError,
    NotPdfError,
    ResourceMissingError,
    TitleMissingError,
)
from app.presentations.repository import PresentationRepository
from app.schemas import (
    Alerte,
    CoursDetail,
    CoursResume,
    InsertionCours,
    NouvelleVersion,
    PositionInsertion,
)
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


def _verifier_hors_seance(connexion: sqlite3.Connection, id_cours: int) -> None:
    """Une présentation non terminée (QM-14) verrouille le cours."""
    if PresentationRepository(connexion).get_unfinished(id_cours) is not None:
        raise CourseLockedError()


def _ecrire_tout_ou_rien(
    connexion: sqlite3.Connection,
    stockage: PdfStorage,
    contenu: bytes,
    ecrire_en_base: Callable[[], tuple[int, int]],
) -> None:
    """Écrit en base puis le fichier ``v{n}.pdf``, dans une seule transaction.

    ``ecrire_en_base`` renvoie ``(id_cours, numero_de_version)``. En cas d'échec, la transaction
    est annulée et le fichier, s'il a été écrit, est supprimé.
    """
    fichier: tuple[int, int] | None = None
    try:
        with transaction(connexion):
            fichier = ecrire_en_base()
            stockage.save(*fichier, contenu)
    except BaseException as erreur:
        if fichier is not None:
            stockage.delete(*fichier)
        if isinstance(erreur, (InternalStorageError, sqlite3.Error, OSError)):
            raise DatabaseUnavailableError() from erreur
        raise


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

    cree: list[tuple[CourseRecord, VersionRecord]] = []

    def ecrire_en_base() -> tuple[int, int]:
        cree.append(
            CourseRepository(connexion).create_course_with_v1(
                titre, proprietaire, len(empreintes), empreintes
            )
        )
        return cree[0][0].id, 1

    _ecrire_tout_ou_rien(connexion, stockage, contenu, ecrire_en_base)
    return cree[0]


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


def _reporter_insertions(
    depot: CourseRepository, ancienne: VersionRecord, nouvelle: VersionRecord
) -> list[Alerte]:
    """Recopie les insertions sur la nouvelle version, au même ``apresPage``.

    Une insertion au-delà de la dernière page y est rattachée et signalée. L'empreinte est
    recalculée sur la page cible de la nouvelle version.
    """
    alertes = []
    for insertion in depot.list_insertions_for_version(ancienne.id):
        page = min(insertion.after_page, nouvelle.page_count)
        id_insertion, _ = depot.add_insertion(
            course_id=nouvelle.course_id,
            version_id=nouvelle.id,
            item_type=insertion.item_type,
            item_id=insertion.item_id,
            after_page=page,
            page_fingerprint=nouvelle.page_fingerprints[max(page, 1) - 1],
        )
        if page != insertion.after_page:
            alertes.append(
                Alerte(
                    id_insertion=id_insertion,
                    type=insertion.item_type,
                    id_quiz=insertion.item_id if insertion.item_type == "QUIZ" else None,
                    id_leaderboard=(
                        insertion.item_id if insertion.item_type == "LEADERBOARD" else None
                    ),
                    titre=insertion.title,
                    apres_page_avant=insertion.after_page,
                    apres_page=page,
                )
            )
    return alertes


def nouvelle_version(
    connexion: sqlite3.Connection,
    stockage: PdfStorage,
    enseignant: str,
    id_cours: int,
    contenu: bytes | None,
    type_mime: str | None,
) -> NouvelleVersion:
    """Archive la version courante et en crée une nouvelle avec les mêmes insertions."""
    depot = CourseRepository(connexion)
    with _base_disponible():
        cours, _ = _cours_de(depot, enseignant, id_cours)
        _verifier_hors_seance(connexion, id_cours)
    empreintes = controler_fichier(contenu, type_mime)
    assert contenu is not None

    alertes: list[Alerte] = []

    def ecrire_en_base() -> tuple[int, int]:
        # Relue dans la transaction : deux envois simultanés ne prennent pas le même numéro.
        ancienne = depot.get_active_version(id_cours)
        if ancienne is None:
            raise InternalStorageError("Aucune version active pour ce cours")
        nouvelle = depot.create_next_version(id_cours, ancienne, len(empreintes), empreintes)
        alertes.extend(_reporter_insertions(depot, ancienne, nouvelle))
        return id_cours, nouvelle.version_number

    _ecrire_tout_ou_rien(connexion, stockage, contenu, ecrire_en_base)
    with _base_disponible():
        version = depot.get_active_version(id_cours)
        assert version is not None
        return NouvelleVersion(**_detail(depot, cours, version).model_dump(), alertes=alertes)


def modifier_structure(
    connexion: sqlite3.Connection,
    enseignant: str,
    id_cours: int,
    positions: list[PositionInsertion],
) -> CoursDetail:
    """Déplace des insertions de la version courante. Tout est vérifié avant d'écrire."""
    depot = CourseRepository(connexion)
    with _base_disponible():
        cours, version = _cours_de(depot, enseignant, id_cours)
        _verifier_hors_seance(connexion, id_cours)
        insertions = depot.list_insertions_for_version(version.id)
        pages_actuelles = {insertion.id: insertion.after_page for insertion in insertions}

    vus: set[int] = set()
    for position in positions:
        if position.id_insertion not in pages_actuelles:
            raise ResourceMissingError(
                "Cet emplacement n'existe pas dans la version courante du cours."
            )
        if position.id_insertion in vus:
            raise InvalidPositionError("Un même emplacement ne peut être placé qu'une fois.")
        if not 1 <= position.apres_page <= version.page_count:
            raise InvalidPositionError(
                f"La position doit être comprise entre 1 et {version.page_count}"
                " (nombre de pages du cours)."
            )
        vus.add(position.id_insertion)

    try:
        with transaction(connexion):
            for position in positions:
                if position.apres_page != pages_actuelles[position.id_insertion]:
                    depot.move_insertion(
                        position.id_insertion,
                        version.id,
                        position.apres_page,
                        version.page_fingerprints[position.apres_page - 1],
                    )
    except InternalStorageError as erreur:
        raise DatabaseUnavailableError() from erreur
    with _base_disponible():
        return _detail(depot, cours, version)


def supprimer_cours(
    connexion: sqlite3.Connection, stockage: PdfStorage, enseignant: str, id_cours: int
) -> None:
    """Supprime le cours et tout ce qui en dépend, en base puis sur le disque."""
    depot = CourseRepository(connexion)
    with _base_disponible():
        _cours_de(depot, enseignant, id_cours)
        _verifier_hors_seance(connexion, id_cours)
    try:
        with transaction(connexion):
            depot.delete_course(id_cours)
    except InternalStorageError as erreur:
        raise DatabaseUnavailableError() from erreur
    # Après le COMMIT seulement : si la base échoue, les PDF du cours restent intacts.
    stockage.delete_course(id_cours)
