from app.errors import ErreurMetier
from app.repositories.cours import Cours, CoursRepository, DepotIndisponible
from app.services import pdf, stockage

TAILLE_MAX_OCTETS = 50 * 1024 * 1024  # limite encore « à définir » dans le cahier de recette


def importer_cours(
    depot: CoursRepository,
    proprietaire: str,
    titre: str,
    contenu: bytes | None,
    type_mime: str | None,
) -> Cours:
    """Contrôle puis enregistre un cours. L'ordre des contrôles est celui de la spec QM-11."""
    titre = titre.strip()
    if not titre:
        raise ErreurMetier(400, "TITRE_MANQUANT", "Veuillez saisir le titre du cours.")
    if contenu is None:
        raise ErreurMetier(400, "FICHIER_MANQUANT", "Veuillez choisir le fichier PDF du cours.")
    if len(contenu) > TAILLE_MAX_OCTETS:
        raise ErreurMetier(
            413,
            "FICHIER_TROP_VOLUMINEUX",
            f"Le fichier dépasse la taille maximale autorisée ({TAILLE_MAX_OCTETS // 1024**2} Mo). "
            "Choisissez un PDF plus léger (compression, découpage).",
        )
    if type_mime != "application/pdf" or not pdf.a_la_signature_pdf(contenu):
        raise ErreurMetier(415, "FORMAT_NON_PDF", "Le fichier doit être au format PDF.")
    empreintes = pdf.calculer_empreintes(contenu)

    id_cours = depot.prochain_id()
    try:
        stockage.ecrire(id_cours, 1, contenu)
        return depot.ajouter(id_cours, titre, proprietaire, empreintes)
    except Exception as erreur:
        stockage.supprimer(id_cours, 1)
        if isinstance(erreur, OSError):
            raise DepotIndisponible() from erreur
        raise
