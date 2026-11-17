from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.utils.crypto import get_random_string

from apps.classification.services import available_requirements
from apps.interviews.models import StudentAttempt
from apps.interviews.services import progress as interview_progress
from apps.inspection.services import summary as inspection_summary
from integrations.pdf.generator import build_report

from . import partidas
from .models import ReportExport
from .services import badge_list, evaluate_badges, lesson_summary, level_for, open_interviews, total_points


@login_required
def dashboard(request):
    user = request.user
    points = total_points(user)
    attempts = user.attempts.select_related("version")
    current = partidas.active(user)
    game = partidas.state(current) if current else None
    # Lo de la partida en curso ya se ve en su tarjeta; aquí solo quedan las prácticas sueltas anteriores.
    skip_attempt = current.attempt_id if current else None
    skip_inspection = current.inspection_id if current else None
    interview_groups = []
    for group in open_interviews(user):
        items = [a for a in [group["latest"], *group["older"]] if a.id != skip_attempt]
        if items:
            interview_groups.append({**group, "latest": items[0], "older": items[1:]})
    lessons = lesson_summary(user)
    lessons["in_progress"] = [lesson for lesson in lessons["in_progress"] if lesson.attempt_id != skip_attempt]
    return render(request, "progress/dashboard.html", {
        "points": points,
        "level": level_for(points),
        "badges": badge_list(user),
        "game": game,
        "history": partidas.history(user),
        "interview_groups": interview_groups,
        "lessons": lessons,
        "classifying": [a for a in attempts.filter(status=StudentAttempt.CLASSIFYING)[:6] if a.id != skip_attempt][:5],
        "use_cases": user.use_cases.all()[:5],
        "open_inspections": [i for i in user.inspections.filter(concluded_at__isnull=True).select_related("exercise")
                             if i.id != skip_inspection],
        "done_inspections": user.inspections.filter(concluded_at__isnull=False).select_related("exercise")[:5],
    })


@login_required
@require_POST
def partida_start(request):
    """«Iniciar nueva partida»: escenario aleatorio y directo a la entrevista."""
    try:
        partida = partidas.start(request.user)
    except partidas.PartidaError as e:
        messages.error(request, str(e))
        return redirect("progress:dashboard")
    messages.success(request, f"¡Nueva partida! Tu escenario es «{partida.attempt.version.title}».")
    return redirect(partidas.continue_url(partida))


@login_required
def partida_continue(request):
    """Lleva a la pantalla de la primera etapa sin terminar de la partida en curso."""
    partida = partidas.active(request.user)
    if partida is None:
        return redirect("progress:dashboard")
    try:
        return redirect(partidas.continue_url(partida))
    except partidas.PartidaError as e:
        messages.error(request, str(e))
        return redirect("progress:dashboard")


@login_required
@require_POST
def partida_abandon(request):
    partida = partidas.active(request.user)
    if partida is not None:
        partidas.abandon(partida)
        messages.info(request, "Abandonaste la partida. Lo que hiciste en ella sigue en Reportes.")
    return redirect("progress:dashboard")


def _report_data(user):
    attempts = []
    for a in user.attempts.filter(status=StudentAttempt.CLASSIFYING).select_related("version"):
        prog = interview_progress(a)
        attempts.append({
            "title": a.version.title, "code": a.version.scenario_code,
            "coverage": f"{prog['asked']}/{prog['max']} preguntas",
            "interview_score": a.interview_score, "precision": a.classification_precision, "hints": a.hints_used,
            "log": [{"question": e.question.text, "answer": e.answer_text, "points": e.question.points}
                    for e in a.log_entries.select_related("question")],
            "classified": a.classifications.count(), "available": available_requirements(a).count(),
            "rows": [{"statement": c.master_requirement.statement_text, "category": c.selected_category,
                      "is_correct": c.is_correct}
                     for c in a.classifications.select_related("master_requirement")],
        })
    use_cases = list(user.use_cases.select_related("diagram"))
    inspections = []
    for ins in user.inspections.filter(concluded_at__isnull=False).select_related("exercise"):
        s = inspection_summary(ins)
        inspections.append({"title": ins.exercise.title, "found": s["found"], "total": s["total"],
                            "precision": ins.precision, "hints": ins.hints_used, "score": ins.score})
    return attempts, use_cases, inspections


@login_required
def report_summary(request):
    attempts, use_cases, inspections = _report_data(request.user)
    has_data = any(a["classified"] for a in attempts) or use_cases or inspections
    return render(request, "reports/summary.html", {
        "attempts": attempts, "use_cases": use_cases, "inspections": inspections, "has_data": has_data,
    })


@login_required
def report_download(request):
    user = request.user
    attempts, use_cases, inspections = _report_data(user)
    attempts = [a for a in attempts if a["classified"]]
    if not (attempts or use_cases or inspections):
        # CU-05 E-1
        messages.error(request, "No hay actividades guardadas para generar el reporte técnico.")
        return redirect("progress:reports")
    report_id = f"{user.username.upper()[:8]}-{get_random_string(6, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')}"
    ReportExport.objects.create(user=user, report_id=report_id)
    evaluate_badges(user)
    points = total_points(user)
    pdf = build_report(report_id=report_id, user=user, level=level_for(points), points=points,
                       attempts=attempts, use_cases=use_cases, inspections=inspections)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="IngeniaLab_Reporte_{report_id}.pdf"'
    return response
