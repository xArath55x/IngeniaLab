from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.api import fail, ok, read_json
from apps.interviews import services as interview_services
from apps.interviews.models import StudentAttempt
from apps.progress.services import evaluate_badges

from . import services


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
    return ok(hint=hint, score=attempt.classification_score, hints_used=attempt.hints_used)
