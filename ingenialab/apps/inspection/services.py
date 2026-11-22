"""AuditEngine (SCI-06): hallazgos contra la clave, pistas y precisión (CU-04)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.locking import lock_and_refresh

from . import guided
from .models import DEFECT_LABELS, InspectionAttempt, InspectionFinding, InspectionFragment

POINTS_PER_DEFECT = 10
WRONG_PENALTY = 3
HINT_PENALTY = 5


class AuditError(Exception):
    pass


def found_defect_ids(attempt):
    return set(attempt.findings.filter(is_correct=True).values_list("fragment_id", flat=True))


def pending_fragments(attempt):
    return attempt.exercise.fragments.exclude(defect_type="").exclude(
        id__in=attempt.findings.order_by().values("fragment_id"),
    )


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
    lock_and_refresh(attempt)
    _ensure_open(attempt)
    if defect_type not in DEFECT_LABELS:
        raise AuditError("Selecciona un tipo de defecto de la lista.")
    try:
        fragment = attempt.exercise.fragments.get(id=fragment_id)
    except (InspectionFragment.DoesNotExist, ValidationError, ValueError):
        raise AuditError("Selecciona una sección del documento.")

    if attempt.findings.filter(fragment=fragment, is_correct=True).exists():
        return {"status": "already_found",
                "message": f"Ya identificaste este defecto: {DEFECT_LABELS[fragment.defect_type]}.",
                "explanation": fragment.explanation, "summary": summary(attempt)}

    attempt.registrations += 1
    if not fragment.defect_type:
        # E-1: defecto inexistente marcado.
        attempt.wrong_registrations += 1
        attempt.save(update_fields=["registrations", "wrong_registrations"])
        return {"status": "no_defect", "message": "El fragmento no contiene defectos conforme a la clave.",
                "explanation": fragment.explanation, "summary": summary(attempt)}

    is_correct = _record_finding(attempt, fragment, defect_type)
    if is_correct:
        return {"status": "correct", "message": f"Correcto: {DEFECT_LABELS[defect_type]}.",
                "explanation": fragment.explanation, "summary": summary(attempt)}
    return {"status": "wrong_type",
            "message": "Inconsistencia detectada: el fragmento sí tiene un defecto, pero de otro tipo.",
            "explanation": "Vuelve a leerlo con atención y compara las definiciones de los tipos de defecto.",
            "summary": summary(attempt)}


def _record_finding(attempt, fragment, defect_type):
    is_correct = fragment.defect_type == defect_type
    if not is_correct:
        attempt.wrong_registrations += 1
    attempt.save(update_fields=["registrations", "wrong_registrations"])
    InspectionFinding.objects.update_or_create(
        attempt=attempt, fragment=fragment, defaults={"selected_type": defect_type, "is_correct": is_correct},
    )
    return is_correct


@transaction.atomic
def answer(attempt, fragment_id, defect_type):
    lock_and_refresh(attempt)
    _ensure_open(attempt)
    if attempt.findings.filter(fragment_id=fragment_id).exists():
        return  # Un doble envío vuelve a la misma corrección.
    fragment = pending_fragments(attempt).first()
    if fragment is None or fragment.id != fragment_id:
        raise AuditError("Responde el fragmento que aparece en pantalla.")
    if defect_type not in dict(guided.options(fragment)):
        raise AuditError("Elige una de las dos correcciones.")
    attempt.registrations += 1
    _record_finding(attempt, fragment, defect_type)


@transaction.atomic
def request_hint(attempt: InspectionAttempt) -> dict:
    lock_and_refresh(attempt)
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
def conclude(attempt: InspectionAttempt, *, after_review=False) -> dict:
    lock_and_refresh(attempt)
    if after_review and attempt.is_concluded:
        return summary(attempt)
    _ensure_open(attempt)
    if after_review and pending_fragments(attempt).exists():
        raise AuditError("Revisa los fragmentos pendientes para terminar.")
    if attempt.registrations == 0 and not after_review:
        # CU-07 E-1 / CP-14 (ACT-313C, BR-11): sin hallazgos no hay precisión que calcular, y concluir daba la
        # insignia «Sin ayuda» por una práctica vacía.
        raise AuditError("Registra al menos un hallazgo antes de concluir la práctica.")
    _, attempt.precision, attempt.score = compute(attempt)
    attempt.concluded_at = timezone.now()
    attempt.save()
    from apps.progress import checkpoints  # Diferido: progress depende de inspection.
    checkpoints.close(attempt.user, "inspection", attempt.id)  # CU-10, RN-01
    return summary(attempt)
