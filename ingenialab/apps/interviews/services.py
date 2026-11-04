"""InterviewEngine (SCI-02): conversación por rondas con el cliente virtual (CU-01).

En cada ronda el estudiante elige una de tres preguntas (muy útil, algo útil, sin aporte),
hasta un máximo de MAX_QUESTIONS. La calidad de cada elección se revela al finalizar.
"""
import math
import random
import uuid

from django.conf import settings
from django.db import transaction, IntegrityError
from django.utils import timezone

from integrations.ai.dialogue import answer as dialogue_answer

from .models import AnswerVariant, InterviewLogEntry, InterviewQuestion, StudentAttempt

MAX_QUESTIONS = 9
# Fracción mínima de rondas para considerar suficiente la entrevista al terminar antes (CU-01 E-1).
THRESHOLD_RATIO = 2 / 3
QUALITY_LABELS = dict(InterviewQuestion.QUALITIES)


class InterviewError(Exception):
    pass


def rounds(version):
    """Números de ronda del escenario, limitados al máximo de preguntas por entrevista."""
    numbers = version.questions.values_list("round_number", flat=True).distinct().order_by("round_number")
    return list(numbers)[:MAX_QUESTIONS]


def asked_rounds(attempt):
    return set(attempt.log_entries.values_list("question__round_number", flat=True))


def next_round(attempt):
    if attempt.status != StudentAttempt.INTERVIEWING:
        return None
    done = asked_rounds(attempt)
    return next((r for r in rounds(attempt.version) if r not in done), None)


def current_options(attempt):
    """Las tres opciones de la ronda en curso, en un orden aleatorio estable por intento."""
    r = next_round(attempt)
    if r is None:
        return []
    options = list(attempt.version.questions.filter(round_number=r))
    random.Random(f"{attempt.id}:{r}").shuffle(options)
    return options


def bank_variant(attempt, question):
    """Variante activa del banco para la pregunta, estable por intento; None si no hay."""
    if not getattr(settings, "INGENIALAB_AI_ANSWER_BANK", True):
        return None
    variants = list(AnswerVariant.for_question(question).filter(is_active=True).order_by("created_at", "id"))
    return random.Random(f"{attempt.id}:{question.round_number}:{question.quality}").choice(variants) if variants else None


def progress(attempt):
    return {"asked": attempt.log_entries.count(), "max": len(rounds(attempt.version))}


def round_topics(version):
    """Tema de cada ronda en orden; todas las opciones de una ronda comparten tema."""
    by_round = dict(version.questions.values_list("round_number", "topic"))
    return [by_round[r] for r in rounds(version)]


def evaluate_threshold(attempt):
    """Compara el avance con el umbral mínimo y lista los temas que aún no se exploran."""
    p = progress(attempt)
    minimum = math.ceil(p["max"] * THRESHOLD_RATIO)
    asked = set(attempt.log_entries.values_list("question__topic", flat=True))
    return {
        **p, "minimum": minimum, "reached": p["asked"] >= minimum,
        "pending_topics": [t for t in round_topics(attempt.version) if t not in asked],
    }


def requirement_index(version):
    return {r.key: str(r.id) for r in version.requirements.all()}


def serialize_entry(entry: InterviewLogEntry, req_ids_by_key):
    q = entry.question
    return {
        "source": entry.response_source,
        "fallback": bool(entry.fallback_reason),
        "question_id": str(q.id),
        "question": q.text,
        "topic": q.topic,
        "time": timezone.localtime(entry.created_at).strftime("%H:%M"),
        "segments": [
            {"text": s["text"], "req_id": req_ids_by_key.get(s.get("req")) if s.get("req") else None}
            for s in (entry.response_segments or q.answer_segments)
        ],
    }


def serialize_options(options):
    # La calidad NO se envía al cliente: se revela solo en el resumen final.
    return [{"id": str(q.id), "text": q.text} for q in options]


def summary(attempt):
    """Resultado de la entrevista con la explicación de cada elección."""
    entries = list(attempt.log_entries.select_related("question"))
    best = {q.round_number: q for q in attempt.version.questions.filter(quality=InterviewQuestion.HIGH)}
    max_rounds = len(rounds(attempt.version))
    max_points = max_rounds * InterviewQuestion.POINTS[InterviewQuestion.HIGH]
    counts = {k: 0 for k, _ in InterviewQuestion.QUALITIES}
    review = []
    for i, e in enumerate(entries, 1):
        q = e.question
        counts[q.quality] += 1
        alt = best.get(q.round_number)
        review.append({
            "n": i, "topic": q.topic, "question": q.text, "quality": q.quality,
            "label": QUALITY_LABELS[q.quality], "points": q.points, "rationale": q.rationale,
            "best": alt.text if alt and alt.id != q.id else None,
        })
    score = sum(r["points"] for r in review)
    pct = round(100 * score / max_points) if max_points else 0
    if pct >= 80:
        rating = ("Entrevistador(a) experto(a)", "Elegiste preguntas abiertas y enfocadas que revelan requisitos concretos.")
    elif pct >= 50:
        rating = ("Buen(a) entrevistador(a)", "Obtuviste información útil, pero algunas preguntas fueron cerradas, vagas o irrelevantes.")
    else:
        rating = ("Sigue practicando", "Muchas preguntas no aportaron requisitos. Prefiere preguntas abiertas sobre necesidades, reglas y restricciones.")
    return {
        "score": score, "max_points": max_points, "percent": pct,
        "asked": len(entries), "max_questions": max_rounds, "counts": counts,
        "rating": rating[0], "rating_text": rating[1], "review": review,
        "premature": attempt.premature_finish,
    }


def _close(attempt, premature):
    attempt.premature_finish = premature
    attempt.interview_score = sum(e.question.points for e in attempt.log_entries.select_related("question"))
    attempt.status = StudentAttempt.CLASSIFYING
    attempt.interview_finished_at = timezone.now()
    attempt.save()


def _dialogue_payload(attempt, entry, replayed=False):
    finished = next_round(attempt) is None
    return {
        "entry": serialize_entry(entry, requirement_index(attempt.version)),
        "options": serialize_options(current_options(attempt)),
        "progress": progress(attempt), "finished": finished,
        "summary": summary(attempt) if finished else None, "replayed": replayed,
    }


@transaction.atomic
def get_dialogue(attempt: StudentAttempt, question_id, allow_replay=False) -> dict:
    """Registra la pregunta elegida, devuelve la respuesta del cliente y la siguiente ronda."""
    try:
        question_id = uuid.UUID(str(question_id))
    except (ValueError, TypeError):
        raise InterviewError("El identificador de la pregunta no es válido.")
    previous = attempt.log_entries.filter(question_id=question_id).select_related("question").first()
    if previous is not None and (attempt.status == StudentAttempt.INTERVIEWING or allow_replay):
        return _dialogue_payload(attempt, previous, replayed=True)
    if attempt.status != StudentAttempt.INTERVIEWING:
        raise InterviewError("La entrevista ya terminó; no se pueden formular nuevas preguntas.")
    options = current_options(attempt)
    question = next((q for q in options if str(q.id) == str(question_id)), None)
    if question is None:
        raise InterviewError("Elige una de las tres preguntas disponibles en esta ronda.")
    # Banco de respuestas redactadas por el LLM de antemano: se sirven al instante. Si no hay, en vivo o catálogo.
    variant = bank_variant(attempt, question)
    if variant is not None:
        segments, source, reason = variant.segments, "ai_bank", ""
    else:
        response = dialogue_answer(question)
        segments, source, reason = response.segments, response.source, response.reason
    try:
        with transaction.atomic():
            entry = InterviewLogEntry.objects.create(
                attempt=attempt, question=question, response_segments=segments,
                response_source=source, fallback_reason=reason,
            )
    except IntegrityError:
        entry = attempt.log_entries.filter(question=question).select_related("question").first()
        if entry is None:
            raise
        attempt.refresh_from_db()
        return _dialogue_payload(attempt, entry, replayed=True)
    finished = next_round(attempt) is None
    if finished:
        _close(attempt, premature=False)
    return _dialogue_payload(attempt, entry)


@transaction.atomic
def finish_interview(attempt: StudentAttempt, confirm_pending: bool) -> dict:
    """Termina la entrevista antes de agotar las preguntas (CU-01 paso 4 / E-1)."""
    if attempt.status != StudentAttempt.INTERVIEWING:
        raise InterviewError("La entrevista ya terminó.")
    if not attempt.log_entries.exists():
        raise InterviewError("Haz al menos una pregunta antes de terminar la entrevista.")
    t = evaluate_threshold(attempt)
    pending = t["max"] - t["asked"]
    if pending and not confirm_pending:
        topics = ", ".join(t["pending_topics"])
        if t["reached"]:
            title = "¿Terminar la entrevista?"
            message = (f"Aún te quedan {pending} pregunta(s) disponibles. Las rondas que no uses no sumarán puntos. "
                       f"Temas sin explorar: {topics}. ¿Deseas terminar de todos modos?")
        else:
            title = "Entrevista incompleta"
            message = (f"Solo has hecho {t['asked']} de {t['max']} preguntas; se recomiendan al menos {t['minimum']} "
                       f"para reunir requisitos suficientes. Temas sin explorar: {topics}. "
                       "Las rondas que no uses no sumarán puntos. ¿Deseas terminar de todos modos?")
        return {
            "needs_confirmation": True, "title": title, "message": message, "pending": pending,
            "below_threshold": not t["reached"], "minimum": t["minimum"], "pending_topics": t["pending_topics"],
        }
    _close(attempt, premature=bool(pending))
    return {"needs_confirmation": False, "summary": summary(attempt)}


@transaction.atomic
def discard_interview(attempt: StudentAttempt):
    """Elimina una entrevista en curso que el estudiante abandonó; las concluidas se conservan."""
    if attempt.status != StudentAttempt.INTERVIEWING:
        raise InterviewError("Solo puede descartarse una entrevista en curso.")
    attempt.delete()


def reset_interview(attempt: StudentAttempt):
    """Vacía la conversación y vuelve a la primera ronda (CU-01 FA-1)."""
    if attempt.status != StudentAttempt.INTERVIEWING:
        raise InterviewError("Solo puede reiniciarse una entrevista en curso.")
    attempt.log_entries.all().delete()
