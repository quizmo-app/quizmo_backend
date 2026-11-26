from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.dependencies import InsertionsDbDep, PdfStorageDep, TeacherDep
from app.schemas import (
    CoursDetail,
    CoursImporte,
    CoursResume,
    NouvelleVersion,
    PositionInsertion,
)
from app.services import cours as service_cours

router = APIRouter(prefix="/api/cours", tags=["cours"])

# Connexion SQLite dont l'échec à l'ouverture devient un 503 BDD_INDISPONIBLE.
Db = InsertionsDbDep


def cours_modifiable(id_cours: int, enseignant: TeacherDep, db: Db) -> None:
    """401, 404, 403 puis 409 : en dépendance, donc avant la validation du corps (400)."""
    service_cours.verifier_cours_modifiable(db, enseignant, id_cours)


COURS_MODIFIABLE = Depends(cours_modifiable)


@router.post("", status_code=201)
def importer_cours(
    enseignant: TeacherDep,
    db: Db,
    stockage: PdfStorageDep,
    # Facultatifs pour FastAPI : leur absence est contrôlée dans l'ordre prévu par la spec.
    titre: Annotated[str, Form()] = "",
    fichier: Annotated[UploadFile, File()] = None,
) -> CoursImporte:
    """Importer un cours PDF (QM-11)."""
    # Un octet de plus que la limite suffit pour détecter le dépassement sans tout charger.
    contenu = fichier.file.read(service_cours.TAILLE_MAX_OCTETS + 1) if fichier else None
    cours, version = service_cours.importer_cours(
        db, stockage, enseignant, titre, contenu, fichier.content_type if fichier else None
    )
    return CoursImporte(id_cours=cours.id, id_version=version.id, nb_pages=version.page_count)


@router.get("")
def lister_cours(enseignant: TeacherDep, db: Db) -> list[CoursResume]:
    """Lister les cours de l'enseignant connecté (QM-17)."""
    return service_cours.lister_cours(db, enseignant)


@router.get("/{id_cours}")
def consulter_cours(id_cours: int, enseignant: TeacherDep, db: Db) -> CoursDetail:
    """Ouvrir un cours : version courante, quiz et leaderboards insérés (QM-17)."""
    return service_cours.consulter_cours(db, enseignant, id_cours)


@router.post("/{id_cours}/versions", dependencies=[COURS_MODIFIABLE])
def nouvelle_version(
    id_cours: int,
    enseignant: TeacherDep,
    db: Db,
    stockage: PdfStorageDep,
    fichier: Annotated[UploadFile, File()] = None,
) -> NouvelleVersion:
    """Mettre à jour le PDF d'un cours : nouvelle version, insertions reportées (QM-17)."""
    contenu = fichier.file.read(service_cours.TAILLE_MAX_OCTETS + 1) if fichier else None
    return service_cours.nouvelle_version(
        db, stockage, enseignant, id_cours, contenu, fichier.content_type if fichier else None
    )


@router.put("/{id_cours}/structure", dependencies=[COURS_MODIFIABLE])
def modifier_structure(
    id_cours: int, positions: list[PositionInsertion], enseignant: TeacherDep, db: Db
) -> CoursDetail:
    """Enregistrer la position des quiz et leaderboards : ``[{idInsertion, apresPage}]`` (QM-17)."""
    return service_cours.modifier_structure(db, enseignant, id_cours, positions)


@router.delete("/{id_cours}", status_code=204, dependencies=[COURS_MODIFIABLE])
def supprimer_cours(
    id_cours: int, enseignant: TeacherDep, db: Db, stockage: PdfStorageDep
) -> Response:
    """Supprimer un cours, ses versions, quiz, leaderboards, insertions et séances (QM-17)."""
    service_cours.supprimer_cours(db, stockage, enseignant, id_cours)
    return Response(status_code=204)
