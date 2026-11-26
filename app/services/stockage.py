import contextlib
import os
from pathlib import Path


def _chemin(id_cours: int, numero: int) -> Path:
    racine = Path(os.environ.get("STORAGE_DIR", "./data/pdf"))
    return racine / str(id_cours) / f"v{numero}.pdf"


def ecrire(id_cours: int, numero: int, contenu: bytes) -> None:
    chemin = _chemin(id_cours, numero)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)


def supprimer(id_cours: int, numero: int) -> None:
    """Annule une écriture, même partielle ; le dossier n'est retiré que s'il est vide."""
    chemin = _chemin(id_cours, numero)
    with contextlib.suppress(OSError):
        chemin.unlink(missing_ok=True)
        chemin.parent.rmdir()
