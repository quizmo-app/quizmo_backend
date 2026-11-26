from dataclasses import dataclass
from itertools import count
from typing import Protocol

from app.errors import ErreurMetier


class DepotIndisponible(ErreurMetier):
    """Le stockage des données ne répond pas."""

    def __init__(self) -> None:
        super().__init__(
            503,
            "BDD_INDISPONIBLE",
            "L'enregistrement est momentanément impossible. "
            "Réessayez dans quelques minutes ou prévenez l'administrateur.",
        )


@dataclass
class Version:
    id_version: int
    numero: int
    courante: bool
    nb_pages: int
    empreintes: list[str]


@dataclass
class Cours:
    id_cours: int
    titre: str
    proprietaire: str
    versions: list[Version]

    @property
    def version_courante(self) -> Version:
        return next(v for v in self.versions if v.courante)


class CoursRepository(Protocol):
    """Accès aux cours. Une implémentation lève DepotIndisponible si elle est en panne."""

    def prochain_id(self) -> int:
        """Réserve un identifiant de cours (le fichier est écrit avant l'enregistrement)."""
        ...

    def ajouter(
        self, id_cours: int, titre: str, proprietaire: str, empreintes: list[str]
    ) -> Cours:
        """Enregistre le cours et sa version n°1, courante."""
        ...

    def lister(self, proprietaire: str) -> list[Cours]: ...


class InMemoryCoursRepository:
    def __init__(self) -> None:
        self._cours: list[Cours] = []
        self._ids_cours = count(1)
        self._ids_version = count(1)

    def prochain_id(self) -> int:
        return next(self._ids_cours)

    def ajouter(
        self, id_cours: int, titre: str, proprietaire: str, empreintes: list[str]
    ) -> Cours:
        version = Version(
            id_version=next(self._ids_version),
            numero=1,
            courante=True,
            nb_pages=len(empreintes),
            empreintes=empreintes,
        )
        cours = Cours(id_cours, titre, proprietaire, [version])
        self._cours.append(cours)
        return cours

    def lister(self, proprietaire: str) -> list[Cours]:
        return [c for c in self._cours if c.proprietaire == proprietaire]


_depot = InMemoryCoursRepository()


def get_cours_repository() -> CoursRepository:
    return _depot
