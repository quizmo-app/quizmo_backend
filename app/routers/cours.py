from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.dependencies import InsertionsDbDep, PdfStorageDep, TeacherDep
from app.schemas import CoursImporte, CoursResume
from app.services import cours as service_cours

router = APIRouter(prefix="/api/cours", tags=["cours"])

# Connexion SQLite dont l'échec à l'ouverture devient un 503 BDD_INDISPONIBLE.
Db = InsertionsDbDep


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
    """Lister les cours de l'enseignant connecté."""
    return [
        CoursResume(
            id_cours=cours.id,
            titre=cours.title,
            version=version.version_number,
            nb_pages=version.page_count,
            nb_quiz=0,
        )
        for cours, version in service_cours.lister_cours(db, enseignant)
    ]
