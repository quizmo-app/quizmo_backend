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


class InsertionCours(ApiModel):
    """Un quiz ou un leaderboard placé après une page de la version courante."""

    id_insertion: int
    type: str
    id_quiz: int | None = None
    id_leaderboard: int | None = None
    titre: str
    apres_page: int
    ordre: int


class CoursDetail(ApiModel):
    """Un cours, sa version courante et ses insertions (QM-17)."""

    id_cours: int
    titre: str
    version: int
    id_version: int
    nb_pages: int
    insertions: list[InsertionCours]


class Alerte(ApiModel):
    """Insertion déplacée sur la dernière page : la nouvelle version a moins de pages."""

    id_insertion: int
    type: str
    id_quiz: int | None = None
    id_leaderboard: int | None = None
    titre: str
    apres_page_avant: int
    apres_page: int


class NouvelleVersion(CoursDetail):
    """Réponse de POST /api/cours/{id}/versions."""

    alertes: list[Alerte]
