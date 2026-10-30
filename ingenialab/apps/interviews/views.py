from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.api import fail, ok, read_json
from apps.progress.services import evaluate_badges
from integrations.ai import dialogue

from . import services
from .models import ScenarioVersion, StudentAttempt


def _badges(user):
    return evaluate_badges(user) if "progress" in settings.INGENIALAB_MODULES else []


def _ask_timeout_ms():
    """Espera del navegador al preguntar: límite del LLM + margen en respuesta libre; 10 s si no."""
    timeout = getattr(settings, "INGENIALAB_AI_FREE_TIMEOUT", 0)
    if (getattr(settings, "INGENIALAB_AI_FREE_ANSWERS", False) and settings.INGENIALAB_AI_MODE == "chat_completions"
            and isinstance(timeout, (int, float)) and 0 < timeout <= dialogue.MAX_FREE_TIMEOUT):
        return max(10000, int((timeout + 5) * 1000))
    return 10000


def _own_attempt(request, attempt_id):
    # Aislamiento de datos: el intento siempre se filtra por el usuario autenticado.
    return get_object_or_404(StudentAttempt, id=attempt_id, user=request.user)


@login_required
def scenario_list(request):
    scenarios = ScenarioVersion.objects.filter(is_active=True)
    attempts = request.user.attempts.select_related("version")
    return render(request, "interviews/scenario_list.html", {
        "scenarios": scenarios, "attempts": attempts, "max_questions": services.MAX_QUESTIONS,
    })


@login_required
@require_POST
def start_attempt(request, version_id):
    version = get_object_or_404(ScenarioVersion, id=version_id, is_active=True)
    attempt = StudentAttempt.objects.create(user=request.user, version=version)
    return redirect("interviews:interview", attempt_id=attempt.id)


@login_required
@require_POST
def discard_attempt(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        services.discard_interview(attempt)
    except services.InterviewError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Se descartó la entrevista de «{attempt.version.title}».")
    return redirect("progress:dashboard")


@login_required
def interview(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    index = services.requirement_index(attempt.version)
    entries = [services.serialize_entry(e, index) for e in attempt.log_entries.select_related("question")]
    finished = attempt.status != StudentAttempt.INTERVIEWING
    return render(request, "interviews/interview.html", {
        "attempt": attempt,
        "entries": entries,
        "options": services.serialize_options(services.current_options(attempt)),
        "progress": services.progress(attempt),
        "topics": services.round_topics(attempt.version),
        "finished": finished,
        "summary": services.summary(attempt) if finished else None,
        "ask_timeout_ms": _ask_timeout_ms(),
    })


@require_POST
def api_ask(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        data = services.get_dialogue(attempt, read_json(request).get("question_id"),
                                     allow_replay=bool(request.headers.get("X-Request-ID")))
    except services.InterviewError as e:
        return fail(str(e))
    if data["finished"]:
        data["badges"] = _badges(request.user)
    return ok(**data)


@require_POST
def api_finish(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        result = services.finish_interview(attempt, bool(read_json(request).get("confirm")))
    except services.InterviewError as e:
        return fail(str(e))
    if not result["needs_confirmation"]:
        result["badges"] = _badges(request.user)
    return ok(**result)


@require_POST
def api_reset(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        services.reset_interview(attempt)
    except services.InterviewError as e:
        return fail(str(e))
    return ok(message="La bitácora se reinició. Puedes comenzar la entrevista de nuevo.")
