"""Unit tests for the QM-12 business rules (RG3, RG4 and error cases E1 to E7)."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from app.quizzes.schemas import LibreQuestion, QcmQuestion, QuizCreateRequest, RelierQuestion
from app.schemas_common import ValidationDetail
from tests.helpers import valid_quiz_payload

PAGE_COUNT = 10
Payload = dict[str, Any]


def check(payload: Payload, page_count: int = PAGE_COUNT) -> list[ValidationDetail]:
    """Validate a raw quiz payload against ``page_count``."""
    return QuizCreateRequest.model_validate(payload).valider(page_count)


def pairs(details: list[ValidationDetail]) -> list[tuple[str, str]]:
    """Extract ``(champ, code)`` pairs from validation details."""
    return [(detail.champ, detail.code) for detail in details]


def test_nominal_quiz_has_no_error() -> None:
    assert check(valid_quiz_payload()) == []


def test_a2_multiple_correct_answers_allowed_with_multiple_choice() -> None:
    payload = valid_quiz_payload()
    configuration = payload["questions"][0]["configuration"]
    configuration["options"][1]["correcte"] = True
    configuration["choixMultiple"] = True
    assert check(payload) == []


def test_a3_ungraded_free_answer_needs_no_accepted_answer() -> None:
    payload = valid_quiz_payload()
    configuration = payload["questions"][1]["configuration"]
    configuration["note"] = False
    configuration["reponsesAcceptees"] = []
    assert check(payload) == []


def test_position_on_last_page_is_valid() -> None:
    assert check(valid_quiz_payload(apres_page=PAGE_COUNT)) == []


def _with_questions(payload: Payload, questions: list[Any]) -> None:
    payload["questions"] = questions


def _drop_questions(payload: Payload) -> None:
    del payload["questions"]


def _qcm_options(payload: Payload, options: list[dict[str, Any]]) -> None:
    payload["questions"][0]["configuration"]["options"] = options


def _many_options(count: int) -> Callable[[Payload], None]:
    options = [{"libelle": f"o{i}", "correcte": i == 0} for i in range(count)]
    return lambda payload: _qcm_options(payload, options)


def _relier_pairs(count: int) -> Callable[[Payload], None]:
    paires = [{"gauche": f"g{i}", "droite": f"d{i}"} for i in range(count)]

    def mutate(payload: Payload) -> None:
        payload["questions"][2]["configuration"]["paires"] = paires

    return mutate


def _set(path: list[str | int], value: Any) -> Callable[[Payload], None]:
    def mutate(payload: Payload) -> None:
        target: Any = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


OPTIONS = "questions[0].configuration.options"
ERROR_CASES = [
    pytest.param(
        lambda p: _with_questions(p, []),
        ("questions", "QUIZ_SANS_QUESTION", "Un quiz doit contenir au moins une question"),
        id="E1-empty-questions",
    ),
    pytest.param(
        _drop_questions,
        ("questions", "QUIZ_SANS_QUESTION", "Un quiz doit contenir au moins une question"),
        id="E1-missing-questions",
    ),
    pytest.param(
        _set(["titre"], "   "),
        ("titre", "CHAMP_OBLIGATOIRE", "Ce champ est obligatoire"),
        id="E2-blank-title",
    ),
    pytest.param(
        _set(["questions", 0, "enonce"], ""),
        ("questions[0].enonce", "CHAMP_OBLIGATOIRE", "Ce champ est obligatoire"),
        id="E2-blank-statement",
    ),
    pytest.param(
        _set(["questions", 0, "configuration", "options", 1, "libelle"], " "),
        (f"{OPTIONS}[1].libelle", "CHAMP_OBLIGATOIRE", "Ce champ est obligatoire"),
        id="E2-blank-option",
    ),
    pytest.param(
        _set(["questions", 1, "configuration", "reponsesAcceptees"], ["ok", ""]),
        (
            "questions[1].configuration.reponsesAcceptees[1]",
            "CHAMP_OBLIGATOIRE",
            "Ce champ est obligatoire",
        ),
        id="E2-blank-accepted-answer",
    ),
    pytest.param(
        _set(["questions", 2, "configuration", "paires", 0, "gauche"], ""),
        (
            "questions[2].configuration.paires[0].gauche",
            "CHAMP_OBLIGATOIRE",
            "Ce champ est obligatoire",
        ),
        id="E2-blank-left-item",
    ),
    pytest.param(
        _set(["questions", 2, "configuration", "paires", 1, "droite"], None),
        (
            "questions[2].configuration.paires[1].droite",
            "CHAMP_OBLIGATOIRE",
            "Ce champ est obligatoire",
        ),
        id="E2-missing-right-item",
    ),
    pytest.param(
        _many_options(1),
        (OPTIONS, "QCM_NOMBRE_OPTIONS", "Un QCM doit avoir entre 2 et 8 options"),
        id="E3-one-option",
    ),
    pytest.param(
        _many_options(9),
        (OPTIONS, "QCM_NOMBRE_OPTIONS", "Un QCM doit avoir entre 2 et 8 options"),
        id="E3-nine-options",
    ),
    pytest.param(
        _set(["questions", 0, "configuration", "options", 0, "correcte"], False),
        (OPTIONS, "QCM_AUCUNE_BONNE_REPONSE", "Un QCM doit avoir au moins une bonne réponse"),
        id="E3-no-correct-answer",
    ),
    pytest.param(
        _set(["questions", 0, "configuration", "options", 1, "correcte"], True),
        (
            OPTIONS,
            "QCM_PLUSIEURS_BONNES_REPONSES",
            "Une seule bonne réponse sans « choix multiple »",
        ),
        id="E3-several-correct-without-multiple-choice",
    ),
    pytest.param(
        _relier_pairs(1),
        (
            "questions[2].configuration.paires",
            "RELIER_NOMBRE_PAIRES",
            "Il faut entre 2 et 8 paires",
        ),
        id="E4-one-pair",
    ),
    pytest.param(
        _relier_pairs(9),
        (
            "questions[2].configuration.paires",
            "RELIER_NOMBRE_PAIRES",
            "Il faut entre 2 et 8 paires",
        ),
        id="E4-nine-pairs",
    ),
    pytest.param(
        _set(["questions", 1, "configuration", "reponsesAcceptees"], []),
        (
            "questions[1].configuration.reponsesAcceptees",
            "LIBRE_SANS_REPONSE_ACCEPTEE",
            "Une question notée doit avoir au moins une réponse acceptée",
        ),
        id="E5-graded-free-answer-without-accepted-answer",
    ),
    pytest.param(
        _set(["questions", 0, "duree"], 4),
        ("questions[0].duree", "DUREE_INVALIDE", "Durée hors des bornes autorisées"),
        id="E6-question-too-short",
    ),
    pytest.param(
        _set(["questions", 0, "duree"], 301),
        ("questions[0].duree", "DUREE_INVALIDE", "Durée hors des bornes autorisées"),
        id="E6-question-too-long",
    ),
    pytest.param(
        _set(["questions", 0, "duree"], None),
        ("questions[0].duree", "DUREE_INVALIDE", "Durée hors des bornes autorisées"),
        id="E6-question-missing-duration",
    ),
    pytest.param(
        _set(["dureeDefaut"], 0),
        ("dureeDefaut", "DUREE_INVALIDE", "Durée hors des bornes autorisées"),
        id="E6-default-duration-out-of-bounds",
    ),
    pytest.param(
        _set(["dureeDefaut"], None),
        ("dureeDefaut", "DUREE_INVALIDE", "Durée hors des bornes autorisées"),
        id="E6-default-duration-missing",
    ),
    pytest.param(
        _set(["apresPage"], 0),
        ("apresPage", "POSITION_INVALIDE", "Position d'insertion invalide"),
        id="E7-page-zero",
    ),
    pytest.param(
        _set(["apresPage"], PAGE_COUNT + 1),
        ("apresPage", "POSITION_INVALIDE", "Position d'insertion invalide"),
        id="E7-page-beyond-last",
    ),
    pytest.param(
        _set(["apresPage"], None),
        ("apresPage", "POSITION_INVALIDE", "Position d'insertion invalide"),
        id="E7-page-missing",
    ),
]


@pytest.mark.parametrize(("mutate", "expected"), ERROR_CASES)
def test_each_rule_reports_its_code_field_and_message(
    mutate: Callable[[Payload], None], expected: tuple[str, str, str]
) -> None:
    payload = valid_quiz_payload()
    mutate(payload)
    champ, code, message = expected
    assert check(payload) == [ValidationDetail(champ=champ, code=code, message=message)]


def test_all_errors_are_reported_together_in_field_order() -> None:
    payload = valid_quiz_payload(apres_page=99)
    payload["titre"] = ""
    payload["questions"][0]["duree"] = 1
    payload["questions"][1]["configuration"]["reponsesAcceptees"] = []
    assert pairs(check(payload)) == [
        ("titre", "CHAMP_OBLIGATOIRE"),
        ("apresPage", "POSITION_INVALIDE"),
        ("questions[0].duree", "DUREE_INVALIDE"),
        ("questions[1].configuration.reponsesAcceptees", "LIBRE_SANS_REPONSE_ACCEPTEE"),
    ]


def test_unknown_question_type_fails_at_parsing() -> None:
    payload = valid_quiz_payload()
    payload["questions"][0]["type"] = "VRAI_FAUX"
    with pytest.raises(ValidationError):
        QuizCreateRequest.model_validate(payload)


def test_qcm_normalized_configuration_assigns_ids_and_defaults() -> None:
    question = QcmQuestion.model_validate(
        {
            "type": "QCM",
            "enonce": "?",
            "duree": 30,
            "configuration": {"options": [{"libelle": "A", "correcte": True}, {"libelle": "B"}]},
        }
    )
    assert question.normalized_configuration() == {
        "options": [
            {"id": "a", "libelle": "A", "correcte": True},
            {"id": "b", "libelle": "B", "correcte": False},
        ],
        "choixMultiple": False,
    }


def test_libre_normalized_configuration_applies_defaults() -> None:
    question = LibreQuestion.model_validate(
        {"type": "LIBRE", "enonce": "?", "duree": 30, "configuration": {"reponsesAcceptees": ["x"]}}
    )
    assert question.normalized_configuration() == {
        "reponsesAcceptees": ["x"],
        "sensibleCasse": False,
        "note": True,
    }


def test_relier_normalized_configuration_keeps_pairs() -> None:
    question = RelierQuestion.model_validate(
        {
            "type": "RELIER",
            "enonce": "?",
            "duree": 30,
            "configuration": {"paires": [{"gauche": "a", "droite": "b"}] * 2},
        }
    )
    assert question.normalized_configuration() == {
        "paires": [{"gauche": "a", "droite": "b"}, {"gauche": "a", "droite": "b"}]
    }


def test_questions_are_immutable() -> None:
    question = QcmQuestion.model_validate({"type": "QCM", "enonce": "?", "duree": 30})
    with pytest.raises(ValidationError):
        question.enonce = "changed"  # type: ignore[misc]
