"""AuditEngine (SCI-06): hallazgos contra la clave, pistas y precisión (CU-04)."""
from django.db import transaction
from django.utils import timezone

from .models import DEFECT_LABELS, InspectionAttempt, InspectionFinding, InspectionFragment

POINTS_PER_DEFECT = 10
WRONG_PENALTY = 3
HINT_PENALTY = 5


class AuditError(Exception):
    pass


def found_defect_ids(attempt):
    return set(attempt.findings.filter(is_correct=True).values_list("fragment_id", flat=True))


def compute(attempt: InspectionAttempt):
    """Precisión = aciertos / registros totales; puntaje = aciertos·10 − errores·3 − pistas·5."""
    correct = len(found_defect_ids(attempt))
    precision = round(100.0 * correct / attempt.registrations, 1) if attempt.registrations else 0.0
    score = max(0, correct * POINTS_PER_DEFECT - attempt.wrong_registrations * WRONG_PENALTY
                - attempt.hints_used * HINT_PENALTY)
    return correct, precision, score


def summary(attempt):
    correct, precision, score = compute(attempt)
    return {
        "found": correct,
        "total": attempt.exercise.defect_count,
        "precision": precision,
        "score": score,
        "hints_used": attempt.hints_used,
        "registrations": attempt.registrations,
        "wrong": attempt.wrong_registrations,
    }


def _ensure_open(attempt):
    if attempt.is_concluded:
        raise AuditError("Esta práctica ya fue concluida.")


@transaction.atomic
def register_finding(attempt: InspectionAttempt, fragment_id, defect_type: str) -> dict:
    _ensure_open(attempt)
    if defect_type not in DEFECT_LABELS:
        raise AuditError("Selecciona un tipo de defecto de la lista.")
    try:
        fragment = attempt.exercise.fragments.get(id=fragment_id)
    except (InspectionFragment.DoesNotExist, ValueError):
        raise AuditError("Selecciona una sección del documento.")

    attempt.registrations += 1
    if not fragment.defect_type:
        # E-1: defecto inexistente marcado.
        attempt.wrong_registrations += 1
        attempt.save(update_fields=["registrations", "wrong_registrations"])
        return {"status": "no_defect", "message": "El fragmento no contiene defectos conforme a la clave.",
                "explanation": fragment.explanation, "summary": summary(attempt)}

    is_correct = fragment.defect_type == defect_type
    if not is_correct:
        attempt.wrong_registrations += 1
    attempt.save(update_fields=["registrations", "wrong_registrations"])
    InspectionFinding.objects.update_or_create(
        attempt=attempt, fragment=fragment, defaults={"selected_type": defect_type, "is_correct": is_correct},
    )
    if is_correct:
        return {"status": "correct", "message": f"Correcto: {DEFECT_LABELS[defect_type]}.",
                "explanation": fragment.explanation, "summary": summary(attempt)}
    return {"status": "wrong_type",
            "message": "Inconsistencia detectada: el fragmento sí tiene un defecto, pero de otro tipo.",
            "explanation": "Vuelve a leerlo con atención y compara las definiciones de los tipos de defecto.",
            "summary": summary(attempt)}


@transaction.atomic
def request_hint(attempt: InspectionAttempt) -> dict:
    _ensure_open(attempt)
    found = found_defect_ids(attempt)
    pending = attempt.exercise.fragments.exclude(defect_type="").exclude(id__in=found).first()
    if pending is None:
        return {"hint": "Ya identificaste todos los defectos. ¡Concluye la práctica!", "fragment_id": None,
                "summary": summary(attempt)}
    attempt.hints_used += 1
    attempt.save(update_fields=["hints_used"])
    return {"hint": f"Revisa la sección {pending.label}: {pending.hint}", "fragment_id": str(pending.id),
            "summary": summary(attempt)}


@transaction.atomic
def conclude(attempt: InspectionAttempt) -> dict:
    _ensure_open(attempt)
    _, attempt.precision, attempt.score = compute(attempt)
    attempt.concluded_at = timezone.now()
    attempt.save()
    return summary(attempt)
