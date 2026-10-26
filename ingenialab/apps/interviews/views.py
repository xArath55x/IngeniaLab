import os
import json

from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.api import fail, ok, read_json
from apps.progress.services import evaluate_badges

from . import services
from .models import ScenarioVersion, StudentAttempt


def _badges(user):
    return evaluate_badges(user) if "progress" in settings.INGENIALAB_MODULES else []


def _own_attempt(request, attempt_id):
    # Aislamiento de datos: el intento siempre se filtra por el usuario autenticado.
    return get_object_or_404(StudentAttempt, id=attempt_id, user=request.user)

"""Carga dinámicamente el catálogo JSON para la sesión de entrevistas.Ruta corregida para apuntar directamente a data/catalog_cu01.json"""

def get_catalog_data():
    # Resolución dinámica y segura de la ruta del archivo JSON.
    file_path = os.path.join(settings.BASE_DIR, 'data', 'catalog_cu01.json')
    
    # Fallback por si BASE_DIR está un nivel por encima (raíz del repo)
    if not os.path.exists(file_path):
        file_path = os.path.join(settings.BASE_DIR, 'ingenialab', 'data', 'catalog_cu01.json')

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "Catálogo no encontrado."}
    except json.JSONDecodeError:
        return {"error": "Error al decodificar el catálogo JSON."}

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
def interview(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    index = services.requirement_index(attempt.version)
    entries = [services.serialize_entry(e, index) for e in attempt.log_entries.select_related("question")]
    finished = attempt.status != StudentAttempt.INTERVIEWING
    catalog_data = get_catalog_data()
    return render(request, "interviews/interview.html", {
        "attempt": attempt,
        "entries": entries,
        "options": services.serialize_options(services.current_options(attempt)),
        "progress": services.progress(attempt),
        "finished": finished,
        "summary": services.summary(attempt) if finished else None,
        "catalog_data": catalog_data
    })


@require_POST
def api_ask(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        data = services.get_dialogue(attempt, read_json(request).get("question_id"))
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

@login_required
def chat_interface(request):
    """Vista principal que carga la interfaz interactiva del catalogo"""
    return render(request, 'interviews/chat.html')
