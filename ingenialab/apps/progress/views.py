from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.api import read_json
from apps.accounts.models import is_teacher
from apps.classification.services import available_requirements
from apps.interviews.models import StudentAttempt
from apps.interviews.services import progress as interview_progress
from apps.inspection import guided
from apps.inspection.services import summary as inspection_summary
from apps.modeling.models import UseCaseLesson
from integrations.pdf.generator import build_report

from . import checkpoints, partidas
from .forms import ReportFeedbackForm, ReportSubmissionForm
from .models import DismissedPractice, Partida, PracticeCheckpoint, ReportExport, ReportFeedback, ReportSubmission
from .services import USE_CASE_POINTS, badge_list, evaluate_badges, lesson_summary, level_for, open_interviews, total_points


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
    dismissed = DismissedPractice.objects.filter(user=user)

    def dismissed_ids(module):
        return dismissed.filter(module=module).values("practice_id")

    interview_groups = []
    for group in open_interviews(user, excluded=dismissed_ids(PracticeCheckpoint.INTERVIEW)):
        items = [a for a in [group["latest"], *group["older"]] if a.id != skip_attempt]
        if items:
            interview_groups.append({**group, "latest": items[0], "older": items[1:]})
    lessons = lesson_summary(user, excluded=dismissed_ids(PracticeCheckpoint.LESSON))
    lessons["in_progress"] = [lesson for lesson in lessons["in_progress"] if lesson.attempt_id != skip_attempt]
    classifying = (attempts.filter(status=StudentAttempt.CLASSIFYING)
                   .exclude(pk=skip_attempt).exclude(pk__in=dismissed_ids(PracticeCheckpoint.CLASSIFICATION))[:5])
    open_inspections = (user.inspections.filter(concluded_at__isnull=True).select_related("exercise")
                        .exclude(pk=skip_inspection).exclude(pk__in=dismissed_ids(PracticeCheckpoint.INSPECTION)))
    use_cases = list(user.use_cases.all()[:5])
    # CU-10: cada práctica que ya lista el tablero muestra si tiene autoguardado o quedó pausada.
    saved, drafts = checkpoints.for_dashboard(user)
    marks = [("interview", a) for g in interview_groups for a in [g["latest"], *g["older"]]]
    marks += [("lesson", l) for l in lessons["in_progress"]] + [("classification", a) for a in classifying]
    marks += [("inspection", i) for i in open_inspections] + [("modeling", uc) for uc in use_cases]
    for module, item in marks:
        item.checkpoint = saved.get((module, str(item.id)))
    return render(request, "progress/dashboard.html", {
        "points": points,
        "level": level_for(points),
        "badges": badge_list(user),
        "game": game,
        "stages": game["stages"] if game else [
            {"label": partidas.STAGE_LABELS[key], "icon": partidas.STAGE_ICONS[key]}
            for key in partidas.STAGE_ORDER
        ],
        "history": partidas.history(user),
        "interview_groups": interview_groups,
        "lessons": lessons,
        "classifying": classifying,
        "drafts": drafts,
        "use_cases": use_cases,
        "open_inspections": open_inspections,
        "done_inspections": user.inspections.filter(concluded_at__isnull=False).select_related("exercise")[:5],
    })


@login_required
@require_POST
def practice_dismiss(request, module, practice_id):
    user = request.user
    active = Partida.objects.filter(user=user, finished_at__isnull=True, abandoned_at__isnull=True)
    active_attempts = active.values("attempt_id")
    practices = {
        PracticeCheckpoint.INTERVIEW: user.attempts.filter(status=StudentAttempt.INTERVIEWING).exclude(pk__in=active_attempts),
        PracticeCheckpoint.CLASSIFICATION: user.attempts.filter(status=StudentAttempt.CLASSIFYING).exclude(pk__in=active_attempts),
        PracticeCheckpoint.LESSON: user.lessons.filter(status=UseCaseLesson.IN_PROGRESS).exclude(attempt_id__in=active_attempts),
        PracticeCheckpoint.INSPECTION: user.inspections.filter(concluded_at__isnull=True)
        .exclude(pk__in=active.filter(inspection_id__isnull=False).values("inspection_id")),
    }
    candidates = practices.get(module)
    if candidates is None or not candidates.filter(pk=practice_id).exists():
        raise Http404
    DismissedPractice.objects.get_or_create(user=user, module=module, practice_id=practice_id)
    messages.success(request, "Práctica eliminada de la lista.")
    return redirect("progress:dashboard")


@login_required
@require_POST
def checkpoint_discard(request, module, key):
    """Descartar un borrador desde el tablero (formulario HTML; la API JSON vive en /api/checkpoints/)."""
    try:
        checkpoints.discard(request.user, module, key)
        messages.success(request, "Borrador descartado.")
    except checkpoints.CheckpointError:
        messages.info(request, "Ese borrador ya no existe.")
    return redirect("progress:dashboard")


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


def _report_data(user, partida=None):
    interviews = user.attempts.filter(status=StudentAttempt.CLASSIFYING).select_related("version")
    use_cases = user.use_cases.select_related("diagram")
    audits = user.inspections.filter(concluded_at__isnull=False).select_related("exercise")
    if partida:
        interviews = interviews.filter(pk=partida.attempt_id)
        use_cases = use_cases.filter(attempt_id=partida.attempt_id)
        audits = audits.filter(pk=partida.inspection_id)

    attempts = []
    for a in interviews:
        prog = interview_progress(a)
        attempts.append({
            "title": a.version.title, "code": a.version.scenario_code,
            "coverage": f"{prog['asked']}/{prog['max']} preguntas",
            "interview_score": a.interview_score, "classification_score": a.classification_score,
            "precision": a.classification_precision, "hints": a.hints_used,
            "log": [{"question": e.question.text, "answer": e.answer_text, "points": e.question.points}
                    for e in a.log_entries.select_related("question")],
            "classified": a.classifications.count(), "available": available_requirements(a).count(),
            "rows": [{"statement": c.master_requirement.statement_text, "category": c.selected_category,
                      "is_correct": c.is_correct}
                     for c in a.classifications.select_related("master_requirement")],
        })
    inspections = []
    for ins in audits:
        s = inspection_summary(ins)
        inspections.append({"title": ins.exercise.title, "found": s["found"], "total": s["total"],
                            "precision": ins.precision, "hints": ins.hints_used, "score": ins.score})
    return attempts, list(use_cases), inspections


def _report_partida(user, partida_id):
    if partida_id is not None:
        return get_object_or_404(Partida.objects.select_related("attempt__version", "inspection__exercise"),
                                 user=user, pk=partida_id, finished_at__isnull=False)


def _partida_overview(partida, data):
    _, use_cases, inspections = data
    lessons = (partida.attempt.lessons.filter(user=partida.user, status=UseCaseLesson.COMPLETED)
               .select_related("reference").order_by("reference__order", "reference_id", "-xp"))
    best = {}
    for lesson in lessons:
        best.setdefault(lesson.reference_id, {"name": lesson.reference.spec["name"], "xp": lesson.xp})
    modeling_points = sum(lesson["xp"] for lesson in best.values()) + len(use_cases) * USE_CASE_POINTS
    return {
        "title": partida.attempt.version.title,
        "points": partida.attempt.total_score + modeling_points + sum(i["score"] for i in inspections),
        "modeling_points": modeling_points,
        "lessons": list(best.values()),
    }


@login_required
def report_summary(request, partida_id=None):
    partida = _report_partida(request.user, partida_id)
    return _render_report_summary(request, _exportable_report_data(request.user, partida), ReportSubmissionForm(), partida)


def _render_report_summary(request, data, submission_form, partida=None):
    attempts, use_cases, inspections = data
    if partida:
        inspection = partida.inspection
        corrections = ([(fragment, guided.example(inspection.exercise, fragment))
                        for fragment in inspection.exercise.fragments.exclude(defect_type="")] if inspection else [])
        return render(request, "reports/partida.html", {
            "partida": partida, "overview": _partida_overview(partida, data), "interview": next(iter(attempts), None),
            "use_cases": use_cases, "inspection": next(iter(inspections), None), "corrections": corrections,
            "submission_form": submission_form,
        })
    return render(request, "reports/summary.html", {
        "attempts": attempts, "use_cases": use_cases, "inspections": inspections, "has_data": any(data),
        "submission_form": submission_form,
        "submissions": _submission_list().filter(export__user=request.user).select_related("teacher"),
    })


def _exportable_report_data(user, partida=None):
    attempts, use_cases, inspections = _report_data(user, partida)
    return (attempts if partida else [a for a in attempts if a["classified"]]), use_cases, inspections


def _report_file(user, data, partida=None):
    attempts, use_cases, inspections = data
    report_id = f"{user.username.upper()[:8]}-{get_random_string(6, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')}"
    points = total_points(user)
    pdf = build_report(report_id=report_id, user=user, level=level_for(points), points=points,
                       attempts=attempts, use_cases=use_cases, inspections=inspections,
                       partida=_partida_overview(partida, data) if partida else None)
    return report_id, points, pdf


def _pdf_download(report_id, pdf):
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="IngeniaLab_Reporte_{report_id}.pdf"'
    return response


@login_required
def report_download(request, partida_id=None):
    user = request.user
    partida = _report_partida(user, partida_id)
    data = _exportable_report_data(user, partida)
    if not any(data):
        # CU-05 E-1
        messages.error(request, "No hay actividades guardadas para generar el reporte técnico.")
        return redirect("progress:reports")
    report_id, _, pdf = _report_file(user, data, partida)
    ReportExport.objects.create(user=user, report_id=report_id)
    evaluate_badges(user)
    return _pdf_download(report_id, pdf)


@login_required
@require_POST
def report_submit(request, partida_id=None):
    user = request.user
    partida = _report_partida(user, partida_id)
    data = _exportable_report_data(user, partida)
    if not any(data):
        messages.error(request, "Completa una actividad para enviar tu reporte.")
        return redirect("progress:reports")
    form = ReportSubmissionForm(request.POST)
    if not form.is_valid():
        return _render_report_summary(request, data, form, partida)
    report_id, points, pdf = _report_file(user, data, partida)
    with transaction.atomic():
        export = ReportExport.objects.create(user=user, report_id=report_id)
        submission = ReportSubmission.objects.create(export=export, teacher=form.cleaned_data["teacher"], points=points, pdf=pdf)
        evaluate_badges(user)
    messages.success(request, "Reporte enviado al profesor.")
    return redirect("progress:submission_detail", pk=submission.pk)


def _submission_list():
    return ReportSubmission.objects.defer("pdf").select_related("export").annotate(
        feedback_count=Count("feedback"),
    ).order_by("-export__created_at", "-pk")


@login_required
@require_GET
@never_cache
def teacher_inbox(request):
    if not is_teacher(request.user):
        raise PermissionDenied
    return render(request, "reports/inbox.html", {
        "submissions": _submission_list().filter(teacher=request.user).select_related("export__user"),
    })


def _get_submission(user, pk, *, include_pdf=False):
    submissions = ReportSubmission.objects.select_related("export__user", "teacher")
    if not include_pdf:
        submissions = submissions.defer("pdf")
    owner = {"teacher": user} if is_teacher(user) else {"export__user": user}
    return get_object_or_404(submissions, pk=pk, **owner)


def _render_submission(request, submission, feedback_form=None):
    return render(request, "reports/submission.html", {
        "submission": submission, "feedback_form": feedback_form, "level": level_for(submission.points),
    })


@login_required
@require_GET
@never_cache
def submission_detail(request, pk):
    submission = _get_submission(request.user, pk)
    form = ReportFeedbackForm() if is_teacher(request.user) else None
    return _render_submission(request, submission, form)


@login_required
@require_GET
@never_cache
def submission_download(request, pk):
    submission = _get_submission(request.user, pk, include_pdf=True)
    return _pdf_download(submission.export.report_id, submission.pdf)


@login_required
@require_POST
@never_cache
def submission_feedback(request, pk):
    if not is_teacher(request.user):
        raise PermissionDenied
    submission = _get_submission(request.user, pk)
    form = ReportFeedbackForm(request.POST)
    if not form.is_valid():
        return _render_submission(request, submission, form)
    ReportFeedback.objects.create(submission=submission, comment=form.cleaned_data["comment"])
    messages.success(request, "Retroalimentación enviada al alumno.")
    return redirect("progress:submission_detail", pk=submission.pk)


# CU-10 · Autoguardado (SDS v3.0 §9.3). ApiSessionGuardMiddleware ya responde 401 JSON sin sesión.
@require_POST
def api_checkpoint_save(request):
    data = read_json(request)
    try:
        checkpoint = checkpoints.save(request.user, data.get("module"), data.get("key"), data.get("revision"),
                                      data.get("payload"), pause=data.get("pause") is True)
    except checkpoints.CheckpointError as e:
        return JsonResponse(e.as_json(), status=e.status)
    return JsonResponse(checkpoints.serialize(checkpoint))


@require_GET
def api_checkpoint_get(request, module, key):
    try:
        checkpoint = checkpoints.get(request.user, module, key)
    except checkpoints.CheckpointError as e:
        return JsonResponse(e.as_json(), status=e.status)
    if checkpoint is None:
        return JsonResponse({"ok": True, "found": False})
    return JsonResponse(checkpoints.serialize(checkpoint, with_payload=True))


@require_POST
def api_checkpoint_discard(request, module, key):
    # ACT-313B: descartar es idempotente. El editor descarta el borrador de un caso de uso cada vez que lo
    # guarda, haya o no borrador; un 404 aquí dejaba un error en la consola del navegador (RNF-04).
    try:
        checkpoints.discard(request.user, module, key)
    except checkpoints.CheckpointError as e:
        if e.code == "no_checkpoint":  # Práctica propia sin borrador.
            return JsonResponse({"ok": True, "discarded": False})
        return JsonResponse(e.as_json(), status=e.status)
    return JsonResponse({"ok": True, "discarded": True})
