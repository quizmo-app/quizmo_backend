import hashlib
from io import BytesIO

from pypdf import PageObject, PdfReader, PdfWriter

from app.exceptions import PdfEncryptedError, PdfUnreadableError

SIGNATURE = b"%PDF"
# La marque de fin doit se trouver dans les derniers octets. pypdf se contente de n'importe quel
# %%EOF du fichier, donc accepte un PDF à plusieurs révisions coupé en plein milieu.
MARQUE_FIN = b"%%EOF"
ZONE_FIN = 1024


def a_la_signature_pdf(contenu: bytes) -> bool:
    """Les premiers octets sont ceux d'un PDF, quelle que soit l'extension."""
    return contenu.startswith(SIGNATURE)


def calculer_empreintes(contenu: bytes) -> list[str]:
    """Une empreinte SHA-256 par page. Refuse un PDF illisible ou chiffré."""
    if MARQUE_FIN not in contenu[-ZONE_FIN:]:
        raise PdfUnreadableError()
    try:
        lecteur = PdfReader(BytesIO(contenu))
        chiffre = lecteur.is_encrypted
        empreintes = [] if chiffre else [_empreinte(page) for page in lecteur.pages]
        # pypdf répare un PDF abîmé en omettant les pages perdues : on compare au nombre annoncé.
        complet = chiffre or len(empreintes) == lecteur.root_object["/Pages"]["/Count"]
    except Exception as erreur:  # un PDF abîmé fait lever à pypdf des exceptions très variées
        raise PdfUnreadableError() from erreur
    if chiffre:
        raise PdfEncryptedError()
    if not empreintes or not complet:
        raise PdfUnreadableError()
    return empreintes


def _empreinte(page: PageObject) -> str:
    # On hache la page isolée avec ses ressources (images, polices). Les annotations sont exclues :
    # un lien vers une autre page entraînerait la copie de tout le document.
    redacteur = PdfWriter()
    redacteur.add_page(page, excluded_keys=["/Annots", "/B"])
    tampon = BytesIO()
    redacteur.write(tampon)
    return hashlib.sha256(tampon.getvalue()).hexdigest()
