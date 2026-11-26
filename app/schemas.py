from app.schemas_common import ApiModel


class CoursImporte(ApiModel):
    """Réponse 201 de l'import (lue par le front : idCours, idVersion, nbPages)."""

    id_cours: int
    id_version: int
    nb_pages: int


class CoursResume(ApiModel):
    """Une ligne du tableau de bord de l'enseignant."""

    id_cours: int
    titre: str
    version: int
    nb_pages: int
    nb_quiz: int
