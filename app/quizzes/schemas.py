"""Polymorphic question models, quiz request/response schemas and QM-12 validation rules."""

from abc import ABC, abstractmethod
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas_common import (
    ApiModel,
    InsertionInfo,
    ValidationDetail,
    duration_detail,
    is_valid_position,
    position_detail,
    required_detail,
)

MIN_DURATION_SECONDS = 5
MAX_DURATION_SECONDS = 300
MIN_QCM_OPTIONS = 2
MAX_QCM_OPTIONS = 8
MIN_RELIER_PAIRS = 2
MAX_RELIER_PAIRS = 8


def _is_blank(value: str | None) -> bool:
    return not isinstance(value, str) or not value.strip()


def _is_valid_duration(value: int | None) -> bool:
    return value is not None and MIN_DURATION_SECONDS <= value <= MAX_DURATION_SECONDS


class QcmOptionInput(ApiModel):
    """One answer choice in a QCM question."""

    id: str | None = None
    libelle: str | None = None
    correcte: bool = False


class QcmConfigInput(ApiModel):
    """Configuration payload for a QCM question."""

    options: list[QcmOptionInput] = Field(default_factory=list)
    choix_multiple: bool = False


class LibreConfigInput(ApiModel):
    """Configuration payload for a free-text question."""

    reponses_acceptees: list[str | None] = Field(default_factory=list)
    sensible_casse: bool = False
    note: bool = True


class RelierPairInput(ApiModel):
    """One matching pair in a RELIER question."""

    gauche: str | None = None
    droite: str | None = None


class RelierConfigInput(ApiModel):
    """Configuration payload for a matching-pairs question."""

    paires: list[RelierPairInput] = Field(default_factory=list)


class BaseQuestionInput(ApiModel, ABC):
    """Common attributes and validation contract for every question type (RG4)."""

    enonce: str | None = None
    duree: int | None = None

    def valider(self, index: int) -> list[ValidationDetail]:
        """Validate common fields and delegate type-specific rules to subclasses."""
        prefix = f"questions[{index}]"
        details: list[ValidationDetail] = []
        if _is_blank(self.enonce):
            details.append(required_detail(f"{prefix}.enonce"))
        if not _is_valid_duration(self.duree):
            details.append(duration_detail(f"{prefix}.duree"))
        details.extend(self._validate_configuration(prefix))
        return details

    @abstractmethod
    def _validate_configuration(self, prefix: str) -> list[ValidationDetail]:
        """Validate question-type specific configuration."""

    @abstractmethod
    def normalized_configuration(self) -> dict[str, Any]:
        """Return canonical JSON-serializable camelCase configuration."""


class QcmQuestion(BaseQuestionInput):
    """Multiple-choice question (QCM)."""

    type: Literal["QCM"]
    configuration: QcmConfigInput = Field(default_factory=QcmConfigInput)

    def _validate_configuration(self, prefix: str) -> list[ValidationDetail]:
        champ = f"{prefix}.configuration.options"
        details: list[ValidationDetail] = []
        options = self.configuration.options
        for opt_idx, option in enumerate(options):
            if _is_blank(option.libelle):
                details.append(required_detail(f"{champ}[{opt_idx}].libelle"))
        if not MIN_QCM_OPTIONS <= len(options) <= MAX_QCM_OPTIONS:
            details.append(
                ValidationDetail(
                    champ=champ,
                    code="QCM_NOMBRE_OPTIONS",
                    message="Un QCM doit avoir entre 2 et 8 options",
                )
            )
            return details
        correct_count = sum(1 for option in options if option.correcte)
        if correct_count == 0:
            details.append(
                ValidationDetail(
                    champ=champ,
                    code="QCM_AUCUNE_BONNE_REPONSE",
                    message="Un QCM doit avoir au moins une bonne réponse",
                )
            )
        elif correct_count > 1 and not self.configuration.choix_multiple:
            details.append(
                ValidationDetail(
                    champ=champ,
                    code="QCM_PLUSIEURS_BONNES_REPONSES",
                    message="Une seule bonne réponse sans « choix multiple »",
                )
            )
        return details

    def normalized_configuration(self) -> dict[str, Any]:
        options = [
            {
                "id": option.id if not _is_blank(option.id) else chr(ord("a") + idx),
                "libelle": option.libelle.strip() if option.libelle else "",
                "correcte": option.correcte,
            }
            for idx, option in enumerate(self.configuration.options)
        ]
        return {"options": options, "choixMultiple": self.configuration.choix_multiple}


class LibreQuestion(BaseQuestionInput):
    """Free-text answer question (LIBRE)."""

    type: Literal["LIBRE"]
    configuration: LibreConfigInput = Field(default_factory=LibreConfigInput)

    def _validate_configuration(self, prefix: str) -> list[ValidationDetail]:
        champ = f"{prefix}.configuration.reponsesAcceptees"
        details: list[ValidationDetail] = []
        accepted = self.configuration.reponses_acceptees
        for ans_idx, answer in enumerate(accepted):
            if _is_blank(answer):
                details.append(required_detail(f"{champ}[{ans_idx}]"))
        if self.configuration.note and not accepted:
            details.append(
                ValidationDetail(
                    champ=champ,
                    code="LIBRE_SANS_REPONSE_ACCEPTEE",
                    message="Une question notée doit avoir au moins une réponse acceptée",
                )
            )
        return details

    def normalized_configuration(self) -> dict[str, Any]:
        return {
            "reponsesAcceptees": [
                answer.strip() for answer in self.configuration.reponses_acceptees if answer
            ],
            "sensibleCasse": self.configuration.sensible_casse,
            "note": self.configuration.note,
        }


class RelierQuestion(BaseQuestionInput):
    """Matching-pairs question (RELIER)."""

    type: Literal["RELIER"]
    configuration: RelierConfigInput = Field(default_factory=RelierConfigInput)

    def _validate_configuration(self, prefix: str) -> list[ValidationDetail]:
        champ = f"{prefix}.configuration.paires"
        details: list[ValidationDetail] = []
        pairs = self.configuration.paires
        for pair_idx, pair in enumerate(pairs):
            if _is_blank(pair.gauche):
                details.append(required_detail(f"{champ}[{pair_idx}].gauche"))
            if _is_blank(pair.droite):
                details.append(required_detail(f"{champ}[{pair_idx}].droite"))
        if not MIN_RELIER_PAIRS <= len(pairs) <= MAX_RELIER_PAIRS:
            details.append(
                ValidationDetail(
                    champ=champ,
                    code="RELIER_NOMBRE_PAIRES",
                    message="Il faut entre 2 et 8 paires",
                )
            )
        return details

    def normalized_configuration(self) -> dict[str, Any]:
        return {
            "paires": [
                {
                    "gauche": pair.gauche.strip() if pair.gauche else "",
                    "droite": pair.droite.strip() if pair.droite else "",
                }
                for pair in self.configuration.paires
            ]
        }


QuestionInput = Annotated[
    QcmQuestion | LibreQuestion | RelierQuestion,
    Field(discriminator="type"),
]


class QuizCreateRequest(ApiModel):
    """Payload to create a quiz and its questions in one call."""

    titre: str | None = None
    duree_defaut: int | None = None
    apres_page: int | None = None
    questions: list[QuestionInput] | None = None

    def valider(self, page_count: int) -> list[ValidationDetail]:
        """Run all QM-12 quiz and per-question validations and return all findings."""
        details: list[ValidationDetail] = []
        if _is_blank(self.titre):
            details.append(required_detail("titre"))
        if not _is_valid_duration(self.duree_defaut):
            details.append(duration_detail("dureeDefaut"))
        if not is_valid_position(self.apres_page, page_count):
            details.append(position_detail("apresPage"))
        if not self.questions:
            details.append(
                ValidationDetail(
                    champ="questions",
                    code="QUIZ_SANS_QUESTION",
                    message="Un quiz doit contenir au moins une question",
                )
            )
            return details
        for idx, question in enumerate(self.questions):
            details.extend(question.valider(idx))
        return details


class QuestionResponse(ApiModel):
    """Persisted question returned in full quiz responses."""

    id_question: int
    ordre: int
    type: str
    enonce: str
    duree: int
    configuration: dict[str, Any]


class QuizDetailResponse(ApiModel):
    """Full quiz payload returned by ``POST /api/cours/{id}/quiz`` and ``GET /api/quiz/{id}``."""

    id_quiz: int
    id_cours: int
    titre: str
    mode: str
    duree_defaut: int
    insertion: InsertionInfo | None = None
    questions: list[QuestionResponse]


class QuizSummaryResponse(ApiModel):
    """Summary entry returned by ``GET /api/cours/{id}/quiz``."""

    id_quiz: int
    titre: str
    nb_questions: int
    apres_page: int | None = None
