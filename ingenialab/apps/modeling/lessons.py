"""Lecciones guiadas de casos de uso (CU-02, estilo Duolingo).

Una lección construye un caso de uso de referencia con ejercicios cortos. Se desbloquea solo si el
estudiante descubrió en su entrevista los requisitos del caso de uso y los clasificó como RF, así los
módulos quedan encadenados: entrevista → clasificación → casos de uso. Las respuestas se califican en
el servidor; el navegador nunca recibe la solución antes de contestar.
"""
import random

from django.db import transaction
from django.utils import timezone

from apps.classification.services import available_requirements

from .models import UseCaseLesson

LIVES = 3
XP_BASE = 10
XP_PER_LIFE = 5
# Parte del caso de uso que construye cada ejercicio, en el orden de la tarjeta «Tu caso de uso».
PARTS = {
    "name": "Nombre", "primary_actor": "Actor principal", "secondary_actors": "Actores secundarios",
    "preconditions": "Precondición", "main_flow": "Flujo principal", "alternate_flows": "Flujo alterno",
    "postconditions": "Postcondición", "relations": "Relaciones",
}


class LessonError(Exception):
    pass


def lesson_status(attempt, reference):
    """Desbloqueo encadenado: cada requisito debe haberse descubierto y clasificado como RF correctamente."""
    keys = reference.requirement_keys
    reqs = {r.key: r for r in attempt.version.requirements.filter(key__in=keys).select_related("question")}
    discovered = set(available_requirements(attempt).filter(key__in=keys).values_list("key", flat=True))
    classified = set(attempt.classifications.filter(
        master_requirement__key__in=keys, selected_category="RF", is_correct=True,
    ).values_list("master_requirement__key", flat=True))
    return {
        "unlocked": all(k in classified for k in keys),
        # De lo no descubierto solo se muestra el tema: el enunciado sería la respuesta de la entrevista.
        "not_discovered": sorted({reqs[k].question.topic for k in keys if k in reqs and k not in discovered}),
        "not_classified": [reqs[k].statement_text for k in keys if k in reqs and k in discovered and k not in classified],
    }


def _choice(rng, ex_id, title, prompt, correct, distractors, explanation, context=None):
    options = [correct, *distractors]
    rng.shuffle(options)
    return {
        "id": ex_id, "type": "choice", "title": title, "prompt": prompt, "context": context or [],
        "options": [{"id": i, "text": t} for i, t in enumerate(options)],
        "answer": options.index(correct), "explanation": explanation,
    }


def build_exercises(reference, statements, seed):
    """Ejercicios de la lección en orden; incluyen la respuesta (solo para el servidor)."""
    rng = random.Random(seed)
    spec, ex = reference.spec, reference.exercises
    name = spec["name"]
    items = [
        _choice(rng, "name", "Del requisito al caso de uso",
                "¿Cuál es el nombre correcto del caso de uso que sale de estos requisitos?",
                name, ex["name"]["distractors"], ex["name"]["explanation"], context=statements),
        _choice(rng, "primary_actor", "¿Quién participa?", f"¿Quién inicia el caso de uso «{name}»?",
                spec["primary_actors"][0], ex["primary_actor"]["distractors"], ex["primary_actor"]["explanation"]),
    ]
    if spec["secondary_actors"]:
        options = [*spec["secondary_actors"], *ex["secondary_actors"]["distractors"]]
        rng.shuffle(options)
        items.append({
            "id": "secondary_actors", "type": "multi", "title": "¿Quién participa?",
            "prompt": "Selecciona los actores secundarios: apoyan al sistema, pero no inician el caso de uso.",
            "context": [], "options": [{"id": i, "text": t} for i, t in enumerate(options)],
            "answer": sorted(options.index(a) for a in spec["secondary_actors"]),
            "explanation": ex["secondary_actors"]["explanation"],
        })
    items.append(_choice(rng, "preconditions", "¿Qué pasa?", "¿Qué debe ser cierto ANTES de empezar?",
                         spec["preconditions"], ex["preconditions"]["distractors"], ex["preconditions"]["explanation"]))
    steps = list(enumerate(spec["main_flow"]))
    while len(steps) > 1 and [i for i, _ in steps] == list(range(len(steps))):
        rng.shuffle(steps)
    items.append({
        "id": "main_flow", "type": "order", "title": "¿Qué pasa?",
        "prompt": "Ordena los pasos del flujo principal tocándolos en orden.",
        "context": [], "options": [{"id": i, "text": t} for i, t in steps],
        "answer": list(range(len(spec["main_flow"]))), "explanation": ex["main_flow"]["explanation"],
    })
    if spec["alternate_flows"]:
        items.append(_choice(rng, "alternate_flows", "¿Qué pasa si…?",
                             "¿Qué pasa si algo sale distinto? Elige el flujo alterno correcto.",
                             spec["alternate_flows"][0], ex["alternate_flows"]["distractors"],
                             ex["alternate_flows"]["explanation"]))
    items.append(_choice(rng, "postconditions", "¿Cómo termina?",
                         "¿Qué queda cierto cuando el caso de uso termina con éxito?",
                         spec["postconditions"], ex["postconditions"]["distractors"], ex["postconditions"]["explanation"]))
    if spec["relations"]:
        items.append({
            "id": "relations", "type": "classify", "title": "Relaciones",
            "prompt": f"¿Qué relación tiene «{name}» con cada caso de uso?", "context": [],
            "options": [{"id": i, "text": r["target"]} for i, r in enumerate(spec["relations"])],
            "categories": [{"id": "include", "text": "«include» (siempre)"}, {"id": "extend", "text": "«extend» (opcional)"}],
            "answer": {str(i): r["type"] for i, r in enumerate(spec["relations"])},
            "explanation": ex["relations"]["explanation"],
        })
    return items


def public(exercise):
    """Versión para el navegador: sin respuesta ni explicación."""
    return {k: v for k, v in exercise.items() if k not in ("answer", "explanation")}


def solution_text(exercise):
    options = {o["id"]: o["text"] for o in exercise["options"]}
    answer = exercise["answer"]
    if exercise["type"] == "choice":
        return [options[answer]]
    if exercise["type"] == "classify":
        labels = {c["id"]: c["text"] for c in exercise["categories"]}
        return [f"{options[int(i)]}: {labels[t]}" for i, t in answer.items()]
    return [options[i] for i in answer]


def is_correct(exercise, answer):
    expected = exercise["answer"]
    kind = exercise["type"]
    try:
        if kind == "choice":
            return int(answer) == expected
        if kind == "multi":
            return sorted(int(a) for a in answer) == expected
        if kind == "order":
            return [int(a) for a in answer] == expected
        if kind == "classify":
            return isinstance(answer, dict) and {str(k): v for k, v in answer.items()} == expected
    except (TypeError, ValueError):
        return False
    return False


def start(user, attempt, reference):
    """Reanuda la lección en curso o crea una nueva si el caso de uso está desbloqueado."""
    if not lesson_status(attempt, reference)["unlocked"]:
        raise LessonError("Esta lección está bloqueada: primero descubre y clasifica sus requisitos funcionales.")
    current = UseCaseLesson.objects.filter(user=user, attempt=attempt, reference=reference,
                                           status=UseCaseLesson.IN_PROGRESS).first()
    if current:
        return current
    statements = list(attempt.version.requirements.filter(key__in=reference.requirement_keys)
                      .order_by("key").values_list("statement_text", flat=True))
    lesson = UseCaseLesson(user=user, attempt=attempt, reference=reference, lives=LIVES)
    lesson.exercises = build_exercises(reference, statements, seed=str(lesson.id))
    lesson.queue = [e["id"] for e in lesson.exercises]
    lesson.save()
    return lesson


def built(lesson):
    """Partes del caso de uso ya construidas; las no resueltas van vacías para no adelantar respuestas."""
    solved = set(lesson.solved)
    return [{"id": e["id"], "label": PARTS[e["id"]], "values": solution_text(e) if e["id"] in solved else None}
            for e in lesson.exercises]


def state(lesson):
    # «lesson_status» y no «status»: IL.api (static/js/app.js) usa «status» para el código HTTP.
    by_id = {e["id"]: e for e in lesson.exercises}
    return {
        "lesson_status": lesson.status, "lives": lesson.lives, "max_lives": LIVES, "xp": lesson.xp,
        "mistakes": lesson.mistakes, "solved": len(lesson.solved), "total": len(lesson.exercises),
        "current": public(by_id[lesson.queue[0]]) if lesson.status == UseCaseLesson.IN_PROGRESS else None,
        "built": built(lesson), "saved": bool(lesson.use_case_id),
    }


@transaction.atomic
def answer(lesson, exercise_id, value):
    lesson = UseCaseLesson.objects.select_for_update().get(pk=lesson.pk)
    if lesson.status != UseCaseLesson.IN_PROGRESS:
        raise LessonError("Esta lección ya terminó.")
    if not lesson.queue or exercise_id != lesson.queue[0]:
        raise LessonError("Responde el ejercicio que tienes en pantalla.")
    exercise = next(e for e in lesson.exercises if e["id"] == exercise_id)
    correct = is_correct(exercise, value)
    lesson.queue.pop(0)
    if correct:
        lesson.solved.append(exercise_id)
    else:
        lesson.lives -= 1
        lesson.mistakes += 1
        # Como en Duolingo, el ejercicio fallado vuelve al final de la lección.
        lesson.queue.append(exercise_id)
    if lesson.lives == 0:
        lesson.status, lesson.finished_at = UseCaseLesson.FAILED, timezone.now()
    elif not lesson.queue:
        lesson.status, lesson.finished_at = UseCaseLesson.COMPLETED, timezone.now()
        lesson.xp = XP_BASE + XP_PER_LIFE * lesson.lives
    lesson.save()
    return {"correct": correct, "explanation": exercise["explanation"],
            "solution": solution_text(exercise), **state(lesson)}
