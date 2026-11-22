from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.api import fail, ok, read_json
from apps.progress import partidas
from apps.progress.services import evaluate_badges

from . import guided, services
from .models import InspectionAttempt, InspectionExercise


def _own(request, attempt_id):
    return get_object_or_404(InspectionAttempt.objects.select_related("exercise"), id=attempt_id, user=request.user)


def _game(attempt):
    partida = getattr(attempt, "partida", None)
    if partida and partida.user_id == attempt.user_id and not partida.abandoned_at:
        return partida


def _report_redirect(attempt, partida):
    if attempt.is_concluded and partida:
        if partida.finished_at or partidas.state(partida)["current"] == partida.DONE:
            return redirect("progress:partida_report", partida_id=partida.id)


@login_required
def exercise_list(request):
    return render(request, "inspection/list.html", {
        "exercises": InspectionExercise.objects.filter(is_active=True),
        "attempts": request.user.inspections.select_related("exercise"),
    })


@login_required
@require_POST
def start(request, exercise_id):
    exercise = get_object_or_404(InspectionExercise, id=exercise_id, is_active=True)
    attempt = InspectionAttempt.objects.create(user=request.user, exercise=exercise)
    return redirect("inspection:inspect", attempt_id=attempt.id)


@login_required
@require_GET
def inspect(request, attempt_id, fragment_id=None):
    attempt = _own(request, attempt_id)
    partida = _game(attempt)
    report = _report_redirect(attempt, partida)
    if report:
        return report
    result = services.summary(attempt)
    context = {"attempt": attempt, "summary": result, "partida": partida}
    if attempt.is_concluded:
        context["corrections"] = [
            (fragment, guided.example(attempt.exercise, fragment))
            for fragment in attempt.exercise.fragments.exclude(defect_type="")
        ]
        return render(request, "inspection/inspect.html", context)

    pending = list(services.pending_fragments(attempt))
    finding = None
    if fragment_id:
        finding = get_object_or_404(attempt.findings.select_related("fragment"), fragment_id=fragment_id)
    fragment = finding.fragment if finding else next(iter(pending), None)
    related_label = guided.CONTEXT.get((attempt.exercise.code, fragment.label)) if fragment else None
    context.update({
        "fragment": fragment,
        "finding": finding,
        "has_next": bool(pending),
        "reviewed": result["total"] - len(pending),
        "related_fragment": attempt.exercise.fragments.filter(label=related_label).first() if related_label else None,
    })
    if fragment and not finding:
        context["options"] = guided.options(fragment)
    if finding:
        context["correction"] = guided.example(attempt.exercise, fragment)
    return render(request, "inspection/inspect.html", context)


@login_required
@require_POST
def guided_answer(request, attempt_id, fragment_id):
    try:
        services.answer(_own(request, attempt_id), fragment_id, request.POST.get("defect_type"))
    except services.AuditError as e:
        messages.error(request, str(e))
        return redirect("inspection:inspect", attempt_id=attempt_id)
    return redirect("inspection:review", attempt_id=attempt_id, fragment_id=fragment_id)


@login_required
@require_POST
def guided_finish(request, attempt_id):
    attempt = _own(request, attempt_id)
    if not attempt.is_concluded:
        try:
            services.conclude(attempt, after_review=True)
        except services.AuditError as e:
            messages.error(request, str(e))
        else:
            evaluate_badges(request.user)
    report = _report_redirect(attempt, _game(attempt))
    if report:
        return report
    return redirect("inspection:inspect", attempt_id=attempt_id)


@require_POST
def api_finding(request, attempt_id):
    data = read_json(request)
    try:
        result = services.register_finding(_own(request, attempt_id), data.get("fragment_id"), data.get("defect_type"))
    except services.AuditError as e:
        return fail(str(e))
    return ok(**result)


@require_POST
def api_hint(request, attempt_id):
    try:
        return ok(**services.request_hint(_own(request, attempt_id)))
    except services.AuditError as e:
        return fail(str(e))


@require_POST
def api_conclude(request, attempt_id):
    try:
        result = services.conclude(_own(request, attempt_id))
    except services.AuditError as e:
        return fail(str(e))
    return ok(summary=result, badges=evaluate_badges(request.user))
