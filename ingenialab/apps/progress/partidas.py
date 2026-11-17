"""Partida única: un escenario recorrido de principio a fin en cuatro etapas (25 % cada una).

Entrevista → Clasificación → Modelado (lecciones guiadas) → Inspección.

El avance se calcula siempre a partir de lo que el alumno ya guardó en cada módulo (bitácora, clasificaciones,
lecciones, hallazgos), así que nunca se desincroniza. Al terminar una etapa se registra su checkpoint con fecha,
y «Continuar partida» lleva a la pantalla de la primera etapa sin terminar.

Reglas para el 100 % de cada etapa:
- Entrevista: cerrada (las 9 preguntas o «Terminar entrevista»).
- Clasificación: todos los enunciados que aparecieron en la bitácora están clasificados.
- Modelado: todas las lecciones del escenario están completadas. En una partida todas se pueden jugar, aunque
  la entrevista no haya descubierto sus requisitos (se muestra un aviso), así que el modelado nunca se salta.
- Inspección: concluida.
"""
import random

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from .models import Partida

STAGE_ORDER = [Partida.INTERVIEW, Partida.CLASSIFICATION, Partida.MODELING, Partida.INSPECTION]
STAGE_LABELS = dict(Partida.STAGES)
STAGE_ICONS = {Partida.INTERVIEW: "💬", Partida.CLASSIFICATION: "🏷️", Partida.MODELING: "📐",
               Partida.INSPECTION: "🔍"}
STAGE_WEIGHT = 100 // len(STAGE_ORDER)


class PartidaError(Exception):
    pass


def active(user):
    """La partida en curso del alumno, o None. Si ya llegó al 100 % se cierra aquí y deja de estar en curso."""
    partida = (Partida.objects.filter(user=user, finished_at__isnull=True, abandoned_at__isnull=True)
               .select_related("attempt__version", "inspection__exercise").first())
    if partida is not None and state(partida)["current"] == Partida.DONE:
        return None
    return partida


def _pick_version(user):
    """Escenario aleatorio entre los que el alumno aún no juega en una partida; si ya jugó todos, cualquiera."""
    from apps.interviews.models import ScenarioVersion

    versions = list(ScenarioVersion.objects.filter(is_active=True))
    if not versions:
        raise PartidaError("No hay escenarios disponibles. Pide al responsable que cargue el contenido.")
    played = set(Partida.objects.filter(user=user).values_list("attempt__version__scenario_code", flat=True))
    fresh = [v for v in versions if v.scenario_code not in played]
    return random.choice(fresh or versions)


def start(user):
    """Crea una partida nueva con un escenario aleatorio. Falla si ya hay una en curso."""
    from apps.interviews.models import StudentAttempt

    if active(user):
        raise PartidaError("Ya tienes una partida en curso. Continúala o abandónala para iniciar otra.")
    version = _pick_version(user)
    try:
        with transaction.atomic():
            attempt = StudentAttempt.objects.create(user=user, version=version)
            return Partida.objects.create(user=user, attempt=attempt)
    except IntegrityError:  # Otra pestaña la creó al mismo tiempo.
        raise PartidaError("Ya tienes una partida en curso. Continúala o abandónala para iniciar otra.")


def abandon(partida):
    """Deja la partida sin terminar. Lo que el alumno hizo en ella se conserva en sus módulos y en Reportes."""
    if not partida.in_progress:
        raise PartidaError("Esta partida ya no está en curso.")
    partida.abandoned_at = timezone.now()
    partida.save(update_fields=["abandoned_at"])


def _ensure_inspection(partida):
    """Asigna el ejercicio de inspección que el alumno ha hecho menos (empate: el primero del catálogo)."""
    from apps.inspection.models import InspectionAttempt, InspectionExercise

    if partida.inspection_id:
        return partida.inspection
    done = dict(InspectionAttempt.objects.filter(user=partida.user).values("exercise")
                .annotate(n=Count("id")).values_list("exercise", "n"))
    exercises = list(InspectionExercise.objects.filter(is_active=True))
    if not exercises:
        raise PartidaError("No hay ejercicios de inspección disponibles.")
    exercise = min(exercises, key=lambda e: done.get(e.id, 0))
    partida.inspection = InspectionAttempt.objects.create(user=partida.user, exercise=exercise)
    partida.save(update_fields=["inspection"])
    return partida.inspection


def _stages(partida):
    """Avance (0 a 1) y detalle de cada etapa, a partir de lo que ya está guardado."""
    from apps.classification.services import available_requirements
    from apps.inspection.services import summary as inspection_summary
    from apps.interviews.models import StudentAttempt
    from apps.interviews.services import progress as interview_progress
    from apps.modeling.models import ReferenceUseCase, UseCaseLesson

    attempt = partida.attempt
    stages = {}

    asked = interview_progress(attempt)
    interview_done = attempt.status != StudentAttempt.INTERVIEWING
    stages[Partida.INTERVIEW] = (1.0 if interview_done else min(asked["asked"] / max(asked["max"], 1), 0.99),
                                 f"{asked['asked']} de {asked['max']} preguntas")

    available = available_requirements(attempt).count()
    classified = attempt.classifications.count()
    if not interview_done:
        stages[Partida.CLASSIFICATION] = (0.0, "Se abre al terminar la entrevista")
    else:
        stages[Partida.CLASSIFICATION] = (1.0 if classified >= available else classified / available,
                                          f"{classified} de {available} enunciados")

    if stages[Partida.CLASSIFICATION][0] < 1:
        stages[Partida.MODELING] = (0.0, "Se abre al clasificar todos los enunciados")
    else:
        refs = list(ReferenceUseCase.objects.filter(version=attempt.version))
        completed = set(UseCaseLesson.objects.filter(attempt=attempt, status=UseCaseLesson.COMPLETED)
                        .values_list("reference_id", flat=True))
        done = sum(1 for r in refs if r.id in completed)
        if not refs:
            stages[Partida.MODELING] = (1.0, "Este escenario no tiene lecciones")
        else:
            stages[Partida.MODELING] = (done / len(refs), f"{done} de {len(refs)} lecciones")

    if stages[Partida.MODELING][0] < 1:
        stages[Partida.INSPECTION] = (0.0, "Se abre al terminar el modelado")
    elif partida.inspection_id is None:
        stages[Partida.INSPECTION] = (0.0, "Lista para empezar")
    else:
        inspection = partida.inspection
        found = inspection_summary(inspection)
        if inspection.concluded_at:
            stages[Partida.INSPECTION] = (1.0, f"{found['found']} de {found['total']} defectos")
        else:
            stages[Partida.INSPECTION] = (min(found["found"] / max(found["total"], 1), 0.99),
                                          f"{found['found']} de {found['total']} defectos")
    return stages


def state(partida, save=True):
    """Estado de la partida para mostrarla; registra los checkpoints nuevos y el cierre (si `save`)."""
    stages = _stages(partida)
    now = timezone.now().isoformat()
    current = next((s for s in STAGE_ORDER if stages[s][0] < 1), Partida.DONE)
    percent = round(sum(STAGE_WEIGHT * stages[s][0] for s in STAGE_ORDER))
    checkpoints = dict(partida.checkpoints or {})
    for s in STAGE_ORDER:
        if stages[s][0] >= 1 and s not in checkpoints:
            checkpoints[s] = now
    changed = (checkpoints != partida.checkpoints or current != partida.stage or percent != partida.percent
               or (current == Partida.DONE and partida.finished_at is None))
    if save and changed and partida.abandoned_at is None:
        partida.checkpoints, partida.stage, partida.percent = checkpoints, current, percent
        if current == Partida.DONE and partida.finished_at is None:
            partida.finished_at = timezone.now()
        partida.save(update_fields=["checkpoints", "stage", "percent", "finished_at"])
    rows = []
    for number, s in enumerate(STAGE_ORDER, start=1):
        value, detail = stages[s]
        rows.append({
            "key": s, "number": number, "label": STAGE_LABELS[s], "icon": STAGE_ICONS[s], "detail": detail,
            "percent": round(value * 100), "done": value >= 1, "current": s == current,
            "checkpoint": checkpoints.get(s),
        })
    return {"partida": partida, "stages": rows, "current": current, "percent": percent,
            "current_label": STAGE_LABELS[current], "current_number": STAGE_ORDER.index(current) + 1
            if current in STAGE_ORDER else len(STAGE_ORDER), "total": len(STAGE_ORDER),
            "title": partida.attempt.version.title}


def continue_url(partida):
    """Pantalla de la primera etapa sin terminar (crea la inspección al llegar a esa etapa)."""
    from apps.modeling.models import UseCaseLesson

    current = state(partida)["current"]
    attempt = partida.attempt
    if current == Partida.INTERVIEW:
        return reverse("interviews:interview", args=[attempt.id])
    if current == Partida.CLASSIFICATION:
        return reverse("classification:classify", args=[attempt.id])
    if current == Partida.MODELING:
        lesson = UseCaseLesson.objects.filter(attempt=attempt, status=UseCaseLesson.IN_PROGRESS).first()
        if lesson:
            return reverse("modeling:lesson", args=[lesson.id])
        return f"{reverse('modeling:lessons')}?attempt={attempt.id}"
    if current == Partida.INSPECTION:
        return reverse("inspection:inspect", args=[_ensure_inspection(partida).id])
    return reverse("progress:dashboard")


def history(user, limit=5):
    """Partidas terminadas o abandonadas, de la más reciente a la más antigua."""
    return list(Partida.objects.filter(user=user).exclude(finished_at__isnull=True, abandoned_at__isnull=True)
                .select_related("attempt__version")[:limit])
