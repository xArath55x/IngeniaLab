"""RequirementService (SCI-03): clasificación RF/RNF, retroalimentación y precisión."""
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.interviews.models import MasterRequirement, StudentAttempt

from .models import StudentClassification

POINTS_PER_CORRECT = 10
HINT_PENALTY = 3
VALID_CATEGORIES = {MasterRequirement.RF, MasterRequirement.RNF}


class ClassificationError(Exception):
    pass


@dataclass
class ClassificationResult:
    classification: StudentClassification
    is_correct: bool
    explanation: str
    reclassified: bool
    precision: float
    score: int


def available_requirements(attempt: StudentAttempt):
    """Declaraciones que aparecen en la bitácora del intento (solo las preguntas formuladas)."""
    asked = attempt.log_entries.values_list("question_id", flat=True)
    return MasterRequirement.objects.filter(version=attempt.version, question_id__in=asked)


def recalculate(attempt: StudentAttempt):
    """Precisión = aciertos / clasificados. Puntaje = aciertos·10 − pistas·3 (mínimo 0)."""
    qs = attempt.classifications.all()
    total = qs.count()
    correct = qs.filter(is_correct=True).count()
    attempt.classification_precision = round(100.0 * correct / total, 1) if total else 0.0
    attempt.classification_score = max(0, correct * POINTS_PER_CORRECT - attempt.hints_used * HINT_PENALTY)
    attempt.save(update_fields=["classification_precision", "classification_score"])
    return attempt


@transaction.atomic
def classify_statement(attempt: StudentAttempt, master_req_id, category: str) -> ClassificationResult:
    if attempt.status != StudentAttempt.CLASSIFYING:
        raise ClassificationError("Debes finalizar la entrevista antes de clasificar requisitos.")
    if category not in VALID_CATEGORIES:
        raise ClassificationError("Debe seleccionar una clasificación válida (RF o RNF) para registrar el requisito.")
    try:
        req = available_requirements(attempt).get(id=master_req_id)
    except (MasterRequirement.DoesNotExist, ValidationError, ValueError):
        raise ClassificationError("Selecciona una declaración resaltable de la bitácora.")

    is_correct = category == req.expected_type
    obj, created = StudentClassification.objects.get_or_create(
        attempt=attempt, master_requirement=req,
        defaults={"selected_category": category, "is_correct": is_correct},
    )
    if not created:
        if obj.selected_category != category:
            obj.times_changed += 1
        obj.selected_category = category
        obj.is_correct = is_correct
        obj.save()

    recalculate(attempt)
    return ClassificationResult(
        classification=obj,
        is_correct=is_correct,
        explanation=req.feedback_explanation,
        reclassified=not created,
        precision=attempt.classification_precision,
        score=attempt.classification_score,
    )


@transaction.atomic
def request_hint(attempt: StudentAttempt, master_req_id) -> str:
    try:
        req = available_requirements(attempt).get(id=master_req_id)
    except (MasterRequirement.DoesNotExist, ValidationError, ValueError):
        raise ClassificationError("Selecciona primero una declaración de la bitácora.")
    attempt.hints_used += 1
    attempt.save(update_fields=["hints_used"])
    recalculate(attempt)
    return req.hint or (
        "Pregúntate: ¿la declaración describe algo que el sistema HACE (una función o servicio) "
        "o una CUALIDAD con la que debe hacerlo (rendimiento, seguridad, usabilidad...)?"
    )
