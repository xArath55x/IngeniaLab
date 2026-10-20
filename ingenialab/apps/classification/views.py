import json
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import IntegrityError
from .models import RequirementClassification

from apps.accounts.api import fail, ok, read_json
from apps.interviews import services as interview_services
from apps.interviews.models import StudentAttempt
from apps.progress.services import evaluate_badges
from . import services
from .models import RequirementClassification

def _own_attempt(request, attempt_id):
    return get_object_or_404(StudentAttempt, id=attempt_id, user=request.user)

def _rows(attempt):
    return [
        {
            "req_id": str(c.master_requirement_id),
            "statement": c.master_requirement.statement_text,
            "category": c.selected_category,
            "is_correct": c.is_correct,
        }
        for c in attempt.classifications.select_related("master_requirement")
    ]


@login_required
def classify(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    if attempt.status == StudentAttempt.INTERVIEWING:
        return redirect("interviews:interview", attempt_id=attempt.id)
    index = interview_services.requirement_index(attempt.version)
    entries = [interview_services.serialize_entry(e, index) for e in attempt.log_entries.select_related("question")]
    return render(request, "classification/classify.html", {
        "attempt": attempt,
        "entries": entries,
        "rows": _rows(attempt),
        "available": services.available_requirements(attempt).count(),
    })


@require_POST
def api_classify(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    data = read_json(request)
    try:
        r = services.classify_statement(attempt, data.get("requirement_id"), data.get("category"))
    except services.ClassificationError as e:
        return fail(str(e))
    return ok(
        is_correct=r.is_correct,
        explanation=r.explanation,
        reclassified=r.reclassified,
        precision=r.precision,
        score=r.score,
        rows=_rows(attempt),
        badges=evaluate_badges(request.user),
    )


@require_POST
def api_hint(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    try:
        hint = services.request_hint(attempt, read_json(request).get("requirement_id"))
    except services.ClassificationError as e:
        return fail(str(e))
    attempt.refresh_from_db()
    return ok(hint=hint, score=attempt.classification_score, hints_used=attempt.hints_used)


@login_required
@require_POST
def save_classification(request, attempt_id):
    """Guarda la clasificación RF/RNF excluyente basada en texto resaltado y maneja duplicados."""
    attempt = _own_attempt(request, attempt_id)
    try:
        data = json.loads(request.body)
        fragment = data.get('text_fragment', '').strip()
        req_type = data.get('req_type')
        
        if not fragment:
            return JsonResponse({'error': 'El fragmento de texto no puede estar vacío.'}, status=400)
        if req_type not in ['RF', 'RNF']:
            return JsonResponse({'error': 'Tipo de clasificación inválido.'}, status=400)
            
        # Creacion del registro (clasificacion excluyente)
        RequirementClassification.objects.create(
            attempt=attempt,
            text_fragment=fragment,
            req_type=req_type
        )
        return JsonResponse({'status': 'success', 'message': f'{req_type} guardado correctamente.'})
        
    except IntegrityError:
        # Falla segura si viola la restriccion UNIQUE de models.py
        return JsonResponse({'error': 'Este fragmento ya fue clasificado previamente. No se permiten duplicados.'}, status=409)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
