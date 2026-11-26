"""Helpers shared by the unit and integration tests."""

from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter


def read_single_page_width(pdf_bytes: bytes) -> float:
    """Parse a 1-page PDF and return its page width."""
    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    first_page: Any = reader.pages[0]
    return float(first_page.mediabox.width)  # pylint: disable=no-member


def make_pdf_bytes(num_pages: int, password: str | None = None) -> bytes:
    """Build a valid blank PDF; every page has a distinct width (distinct fingerprint)."""
    writer = PdfWriter()
    for index in range(num_pages):
        writer.add_blank_page(width=200 + index, height=300)
    if password is not None:
        writer.encrypt(password)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def valid_quiz_payload(apres_page: int = 4) -> dict[str, Any]:
    """Return the nominal QM-12 request body (QCM + LIBRE + RELIER)."""
    return {
        "titre": "Les bases du SQL",
        "dureeDefaut": 30,
        "apresPage": apres_page,
        "questions": [
            {
                "type": "QCM",
                "enonce": "Quelle commande lit des données ?",
                "duree": 30,
                "configuration": {
                    "options": [
                        {"id": "a", "libelle": "SELECT", "correcte": True},
                        {"id": "b", "libelle": "DELETE", "correcte": False},
                    ],
                    "choixMultiple": False,
                },
            },
            {
                "type": "LIBRE",
                "enonce": "Comment s'appelle l'identifiant unique d'une ligne ?",
                "duree": 45,
                "configuration": {
                    "reponsesAcceptees": ["clé primaire", "primary key"],
                    "sensibleCasse": False,
                    "note": True,
                },
            },
            {
                "type": "RELIER",
                "enonce": "Reliez chaque commande à son rôle",
                "duree": 60,
                "configuration": {
                    "paires": [
                        {"gauche": "INSERT", "droite": "Ajouter"},
                        {"gauche": "UPDATE", "droite": "Modifier"},
                    ]
                },
            },
        ],
    }
