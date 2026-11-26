"""Domain exceptions and their translation into the uniform JSON error envelope."""

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas_common import ValidationDetail, detail_from_pydantic_error

LOGGER = logging.getLogger(__name__)


class AppError(Exception):
    """Base class: every subclass maps to one HTTP status and one error code."""

    status_code = 500
    code = "ERREUR_INTERNE"
    default_message = "Une erreur interne est survenue"
    default_action: str | None = None

    def __init__(self, message: str | None = None, action: str | None = None) -> None:
        self.message = message or self.default_message
        self.action = action if action is not None else self.default_action
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        """JSON body of the error response."""
        payload: dict[str, Any] = {"erreur": self.code, "message": self.message}
        if self.action is not None:
            payload["action"] = self.action
        return payload


class AuthenticationError(AppError):
    """Missing, expired or invalid session (QM-12 E9 / QM-14)."""

    status_code = 401
    code = "NON_AUTHENTIFIE"
    default_message = "Session absente ou expirée"


class SessionExpiredError(AppError):
    """Missing, expired or invalid session (QM-13 CA7)."""

    status_code = 401
    code = "SESSION_EXPIREE"
    default_message = "Session absente ou expirée"
    default_action = "Se reconnecter (CU1.1) puis relancer l'insertion"


class AccessDeniedError(AppError):
    """The resource belongs to another teacher."""

    status_code = 403
    code = "ACCES_REFUSE"
    default_message = "Accès refusé"


class ValidationFailedError(AppError):
    """Business or input validation failure carrying one detail per problem."""

    status_code = 400
    code = "VALIDATION"
    default_message = "La requête contient des erreurs"

    def __init__(self, details: Sequence[ValidationDetail], message: str | None = None) -> None:
        super().__init__(message)
        self.details = tuple(details)

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload["details"] = [detail.model_dump() for detail in self.details]
        return payload


class InvalidPageError(AppError):
    """Insertion page outside 0..page_count (QM-13 CA4)."""

    status_code = 400
    code = "PAGE_INVALIDE"
    default_message = (
        "La page d'insertion doit être comprise entre 0 et le nombre de pages du cours"
    )
    default_action = "Choisir une page du cours"


class InvalidQuizForInsertionError(AppError):
    """Quiz has no question or belongs to another course (QM-13 CA5)."""

    status_code = 422
    code = "QUIZ_INVALIDE"
    default_message = "Le quiz doit appartenir à ce cours et contenir au moins une question"
    default_action = "Choisir un autre quiz ou lui ajouter une question (CU1.3)"


class ResourceNotFoundError(AppError):
    """Base class of the 404 errors."""

    status_code = 404
    code = "INTROUVABLE"
    default_message = "Ressource introuvable"


class ResourceMissingError(ResourceNotFoundError):
    """Course, version or quiz not found (QM-13 CA7)."""

    code = "RESSOURCE_INTROUVABLE"
    default_message = "Cours, version ou quiz introuvable"
    default_action = "Recharger le déroulé du cours"


class CourseNotFoundError(ResourceNotFoundError):
    """Unknown course."""

    code = "COURS_INTROUVABLE"
    default_message = "Cours introuvable"


class QuizNotFoundError(ResourceNotFoundError):
    """Unknown quiz."""

    code = "QUIZ_INTROUVABLE"
    default_message = "Quiz introuvable"


class VersionNotFoundError(ResourceNotFoundError):
    """Unknown course version."""

    code = "VERSION_INTROUVABLE"
    default_message = "Version du cours introuvable"


class PageNotFoundError(ResourceNotFoundError):
    """Page outside the version."""

    code = "PAGE_INTROUVABLE"
    default_message = "Page introuvable"


class PresentationNotFoundError(ResourceNotFoundError):
    """No presentation in progress for the course."""

    code = "PRESENTATION_INTROUVABLE"
    default_message = "Aucune présentation en cours pour ce cours"


class ConflictError(AppError):
    """Base class of the 409 errors."""

    status_code = 409
    code = "CONFLIT"
    default_message = "Action impossible dans l'état actuel"


class NonCurrentVersionError(ConflictError):
    """Target version is archived, not current (QM-13 CA6)."""

    code = "VERSION_NON_COURANTE"
    default_message = "Cette version n'est pas la version courante"
    default_action = "Passer sur la version courante"


class QuizAlreadyInsertedError(ConflictError):
    """Quiz already inserted into this version (QM-13 CA5)."""

    code = "QUIZ_DEJA_INSERE"
    default_message = "Ce quiz est déjà inséré dans cette version"
    default_action = "Déplacer l'insertion existante ou choisir un autre quiz"


class CourseArchivedError(ConflictError):
    """Archived courses cannot be presented."""

    code = "COURS_ARCHIVE"
    default_message = "Ce cours est archivé"


class PdfUnavailableError(ConflictError):
    """The PDF file is missing from the storage volume."""

    code = "PDF_INDISPONIBLE"
    default_message = "Le fichier PDF du cours est indisponible"


class PresentationStateError(ConflictError):
    """The requested action is not allowed in the current presentation state."""

    code = "PRESENTATION_ETAT_INVALIDE"
    default_message = "Action impossible dans l'état actuel de la présentation"


class DatabaseUnavailableError(AppError):
    """Database connection or transaction unavailable (QM-13 CA8)."""

    status_code = 503
    code = "BDD_INDISPONIBLE"
    default_message = "Réessayez dans quelques minutes ou prévenez l'administrateur"
    default_action = "Réessayer dans quelques minutes ou prévenir l'administrateur"


class InternalStorageError(AppError):
    """Database or file-system failure (QM-12 E10); the transaction has been rolled back."""


class TitleMissingError(AppError):
    """Course title absent, empty or blank (QM-11)."""

    status_code = 400
    code = "TITRE_MANQUANT"
    default_message = "Veuillez saisir le titre du cours."


class FileMissingError(AppError):
    """No PDF file in the upload (QM-11)."""

    status_code = 400
    code = "FICHIER_MANQUANT"
    default_message = "Veuillez choisir le fichier PDF du cours."


class FileTooLargeError(AppError):
    """Uploaded file above the size limit (QM-11)."""

    status_code = 413
    code = "FICHIER_TROP_VOLUMINEUX"
    default_message = "Le fichier dépasse la taille maximale autorisée."


class NotPdfError(AppError):
    """MIME type or file signature is not PDF (QM-11)."""

    status_code = 415
    code = "FORMAT_NON_PDF"
    default_message = "Le fichier doit être au format PDF."


class PdfUnreadableError(AppError):
    """Corrupted or truncated PDF (QM-11)."""

    status_code = 422
    code = "PDF_ILLISIBLE"
    default_message = (
        "Le PDF est illisible (fichier abîmé ou incomplet). "
        "Réexportez-le depuis le document source, puis réessayez."
    )


class PdfEncryptedError(AppError):
    """Password-protected PDF (QM-11)."""

    status_code = 422
    code = "PDF_CHIFFRE"
    default_message = "Le PDF est protégé par un mot de passe. Fournissez un PDF non protégé."


def register_exception_handlers(application: FastAPI) -> None:
    """Install the handlers producing ``{"erreur", "message", "details"?}`` bodies."""

    @application.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        if isinstance(exc, (InternalStorageError, DatabaseUnavailableError)):
            LOGGER.error("Storage failure", exc_info=exc)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [detail_from_pydantic_error(error) for error in exc.errors()]
        error = ValidationFailedError(details)
        return JSONResponse(status_code=error.status_code, content=error.to_payload())

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"erreur": f"HTTP_{exc.status_code}", "message": str(exc.detail)},
            headers=exc.headers,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        LOGGER.error("Unhandled error", exc_info=exc)
        error = InternalStorageError()
        return JSONResponse(status_code=error.status_code, content=error.to_payload())
