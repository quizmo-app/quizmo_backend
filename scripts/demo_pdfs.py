"""Génère les fichiers de démonstration QM-11 : uv run python scripts/demo_pdfs.py"""

import struct
import zlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

DOSSIER = Path(__file__).resolve().parent.parent / "demo_pdfs"


def faire_pdf(mot_de_passe: str | None = None) -> bytes:
    redacteur = PdfWriter()
    for i in range(10):
        redacteur.add_blank_page(width=595 + i, height=842)
    if mot_de_passe:
        redacteur.encrypt(mot_de_passe, algorithm="AES-256")
    tampon = BytesIO()
    redacteur.write(tampon)
    return tampon.getvalue()


def faire_png() -> bytes:
    def bloc(nom: bytes, donnees: bytes) -> bytes:
        corps = nom + donnees
        return struct.pack(">I", len(donnees)) + corps + struct.pack(">I", zlib.crc32(corps))

    entete = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", entete) + bloc(b"IDAT", pixels) + bloc(b"IEND", b"")
    )


if __name__ == "__main__":
    pdf = faire_pdf()
    fichiers = {
        "valide_10_pages.pdf": pdf,
        "png_renomme.pdf": faire_png(),
        "corrompu.pdf": pdf[: len(pdf) // 2],
        "chiffre.pdf": faire_pdf(mot_de_passe="secret"),
    }
    DOSSIER.mkdir(exist_ok=True)
    for nom, contenu in fichiers.items():
        (DOSSIER / nom).write_bytes(contenu)
        print(DOSSIER / nom)
