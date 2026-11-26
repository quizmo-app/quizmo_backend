from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.auth_bouchon import Enseignant, get_current_user
from app.repositories.cours import CoursRepository, get_cours_repository
from app.schemas import CoursImporte, CoursResume
from app.services import cours as service_cours

router = APIRouter(prefix="/api/cours", tags=["cours"])

EnseignantConnecte = Annotated[Enseignant, Depends(get_current_user)]
Depot = Annotated[CoursRepository, Depends(get_cours_repository)]


@router.post("", status_code=201)
def importer_cours(
    enseignant: EnseignantConnecte,
    depot: Depot,
    # Facultatifs pour FastAPI : leur absence est contrôlée dans l'ordre prévu par la spec.
    titre: Annotated[str, Form()] = "",
    fichier: Annotated[UploadFile, File()] = None,
) -> CoursImporte:
    # Un octet de plus que la limite suffit pour détecter le dépassement sans tout charger.
    contenu = fichier.file.read(service_cours.TAILLE_MAX_OCTETS + 1) if fichier else None
    cours = service_cours.importer_cours(
        depot, enseignant.login, titre, contenu, fichier.content_type if fichier else None
    )
    version = cours.version_courante
    return CoursImporte(
        id_cours=cours.id_cours, id_version=version.id_version, nb_pages=version.nb_pages
    )


@router.get("")
def lister_cours(enseignant: EnseignantConnecte, depot: Depot) -> list[CoursResume]:
    return [
        CoursResume(
            id_cours=cours.id_cours,
            titre=cours.titre,
            version=cours.version_courante.numero,
            nb_pages=cours.version_courante.nb_pages,
            nb_quiz=0,  # les quiz n'existent pas encore
        )
        for cours in depot.lister(enseignant.login)
    ]
