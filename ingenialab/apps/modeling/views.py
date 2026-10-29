import base64
import json
import uuid
from time import perf_counter

from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.api import fail, ok, read_json
from apps.interviews.models import StudentAttempt
from apps.progress.services import evaluate_badges
from integrations.plantuml import service as plantuml
from integrations.plantuml.builder import build_usecase_diagram

from . import lessons as lesson_engine
from . import validators
from .models import GeneratedDiagram, ReferenceUseCase, UseCaseLesson, UseCaseSpecification
from .forms import UseCaseForm


def _finished_attempts(user):
    return user.attempts.filter(status=StudentAttempt.CLASSIFYING).select_related("version")


@login_required
def usecase_list(request):
    return render(request, "modeling/list.html", {
        "use_cases": request.user.use_cases.select_related("attempt__version"),
        "can_model": _finished_attempts(request.user).exists(),
    })


def _guide(attempts):
    """Requisitos clasificados de cada entrevista terminada, para guiar la redacción del caso de uso."""
    return [{
        "id": str(a.id),
        "label": f"{a.version.title} ({a.started_at:%d/%m/%Y})",
        "system": a.version.title,
        "requirements": [
            {"key": c.master_requirement.key, "statement": c.master_requirement.statement_text,
             "category": c.selected_category}
            for c in a.classifications.select_related("master_requirement")
        ],
    } for a in attempts]


@login_required
def editor(request, uc_id=None):
    attempts = _finished_attempts(request.user)
    if not attempts.exists():
        # Precondición CU-02: al menos una entrevista completada.
        messages.warning(request, "Para modelar casos de uso primero completa al menos una entrevista en el módulo de Elicitación.")
        return redirect("modeling:list")
    uc = get_object_or_404(UseCaseSpecification, id=uc_id, user=request.user) if uc_id else None
    reference = uc.attempt if uc and uc.attempt_id else attempts.first()
    # Al terminar una lección, el editor se abre con el caso de uso que se armó en ella.
    lesson = None
    if not uc and request.GET.get("leccion"):
        try:
            lesson = UseCaseLesson.objects.select_related("reference", "attempt").get(
                id=request.GET["leccion"], user=request.user, status=UseCaseLesson.COMPLETED)
            reference = lesson.attempt
        except (UseCaseLesson.DoesNotExist, ValidationError):
            lesson = None
    if not uc and request.GET.get("attempt"):
        try:
            reference = get_object_or_404(attempts, id=request.GET["attempt"])
        except ValidationError:
            return HttpResponse("La entrevista seleccionada no es válida.", status=400)
    guide = _guide(attempts)
    return render(request, "modeling/editor.html", {
        "uc": uc,
        "form_data": uc.as_form_data() if uc else (
            {**lesson.reference.spec, "attempt_id": str(lesson.attempt_id)} if lesson else None),
        "lesson": lesson,
        "svg": uc.diagram.svg if uc and hasattr(uc, "diagram") else "",
        "guide": guide,
        "reference_attempt": reference,
        "validation_rules": validators.RULES,
    })


def _read_payload(request):
    try:
        if len(request.body) > 160_000:
            return None, fail("La plantilla excede el tamaño permitido.", status=413)
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None, fail("Envía un objeto JSON válido.")
    if not isinstance(data, dict):
        return None, fail("Envía un objeto JSON válido.")
    return data, None


def _checked_form(request, data):
    form = UseCaseForm(data=data, user=request.user)
    valid = form.is_valid()
    warnings = validators.suggestions(form.cleaned_data)
    if not valid:
        return form, fail(validators.REQUIRED_MESSAGE, errors=form.error_messages(), warnings=warnings)
    if not _finished_attempts(request.user).exists():
        return form, fail("Primero completa una entrevista para modelar casos de uso.", status=409)
    return form, None


@login_required
@require_POST
def api_validate(request):
    """Validación de ACT-207A sin invocar PlantUML ni escribir en la BD."""
    data, error = _read_payload(request)
    if error is not None: return error
    form, error = _checked_form(request, data)
    if error is not None: return error
    return ok(spec=form.cleaned_data, numbered_steps=form.numbered_steps(),
              warnings=validators.suggestions(form.cleaned_data),
              message="Plantilla válida: estructura completa y pasos consecutivos.")


@login_required
@require_POST
def api_generate(request):
    data, error = _read_payload(request)
    if error is not None: return error
    form, error = _checked_form(request, data)
    if error is not None: return error
    spec = form.cleaned_data
    code = build_usecase_diagram(spec)
    format = data.get("format", "svg")
    if not isinstance(format, str) or format not in plantuml.FORMATS:
        return fail("Formato permitido: svg o png.")
    started = perf_counter()
    certification_ms = 0
    try:
        # Separar fases explícitas: la certificación SVG queda en caché antes del PNG.
        # Cada render mantiene su presupuesto y la latencia total se informa aparte.
        if format == "png":
            certified = plantuml.render(code, "svg")
            certification_ms = certified.duration_ms
            svg = certified.svg
            result = plantuml.render(code, "png")
        else:
            result = plantuml.render(code, "svg")
            svg = result.svg
    except plantuml.PlantUMLError as e:
        return fail(str(e), status=e.status, error=e.code)
    total_ms = round((perf_counter() - started) * 1000, 3)
    return ok(plantuml_code=code, svg=svg, engine=result.engine, cached=result.cached,
              spec=spec, warnings=validators.suggestions(spec), code_hash=result.code_hash,
              duration_ms=result.duration_ms, total_duration_ms=total_ms, svg_certification_ms=certification_ms,
              cache_warning=result.warning, image_format=format,
              png_data_uri="data:image/png;base64,"+base64.b64encode(result.data).decode("ascii") if format=="png" else "")



def _replay_saved(uc, spec, user):
    if uc.user_id != user.pk or uc.as_form_data() != spec or not hasattr(uc, "diagram"):
        return fail("La solicitud ya se utilizó con otros datos. Conserva el borrador e inicia un nuevo guardado.", status=409)
    return ok(id=str(uc.id), plantuml_code=uc.plantuml_code, svg=uc.diagram.svg,
              engine=uc.diagram.engine, warnings=validators.suggestions(spec), cached=True,
              duration_ms=0, code_hash=uc.diagram.code_hash, cache_warning="", spec=spec,
              message="La especificación ya estaba guardada.", badges=[], replayed=True)


@login_required
@require_POST
@transaction.atomic
def api_save(request):
    data, error = _read_payload(request)
    if error is not None: return error
    form, error = _checked_form(request, data)
    if error is not None: return error
    # Resolver el identificador antes de invocar el renderizador.
    uc = None
    if data.get("id"):
        try: uc_id = uuid.UUID(str(data["id"]))
        except ValueError: return fail("El identificador del caso de uso no es válido.")
        uc = get_object_or_404(UseCaseSpecification, id=uc_id, user=request.user)
    spec = form.cleaned_data
    request_id = None
    if uc is None and request.headers.get("X-Request-ID"):
        try:
            request_id = uuid.UUID(request.headers["X-Request-ID"])
        except ValueError:
            return fail("El identificador de solicitud no es válido.")
        previous = UseCaseSpecification.objects.select_related("diagram").filter(id=request_id).first()
        if previous is not None:
            return _replay_saved(previous, spec, request.user)
    code = build_usecase_diagram(spec)
    try: result = plantuml.render(code)
    except plantuml.PlantUMLError as e:
        return fail(str(e), status=e.status, error=e.code)
    warnings = validators.suggestions(spec)
    attempt = None
    if spec["attempt_id"]:
        attempt = _finished_attempts(request.user).filter(id=spec["attempt_id"]).first()
    fields = {
        "attempt": attempt,
        "name": spec["name"],
        "system_name": spec["system_name"],
        "actors": {"primary": spec["primary_actors"], "secondary": spec["secondary_actors"]},
        "preconditions": spec["preconditions"],
        "main_flow": spec["main_flow"],
        "alternate_flows": spec["alternate_flows"],
        "postconditions": spec["postconditions"],
        "relations": spec["relations"],
        "plantuml_code": code,
    }
    if uc is not None:
        # Actualización sin duplicar registros (CU-02 FA-1).
        for k, v in fields.items():
            setattr(uc, k, v)
        uc.save()
    elif request_id is not None:
        uc, created = UseCaseSpecification.objects.get_or_create(
            id=request_id, defaults={"user": request.user, **fields})
        if not created:
            return _replay_saved(uc, spec, request.user)
    else:
        uc = UseCaseSpecification.objects.create(user=request.user, **fields)
    GeneratedDiagram.objects.update_or_create(
        use_case=uc, defaults={"code_hash": result.code_hash, "svg": result.svg, "engine": result.engine},
    )
    return ok(id=str(uc.id), plantuml_code=code, svg=result.svg, engine=result.engine, warnings=warnings,
              cached=result.cached, duration_ms=result.duration_ms, code_hash=result.code_hash,
              cache_warning=result.warning, spec=spec, message="Especificación guardada correctamente en tu cuenta.", badges=evaluate_badges(request.user))


@login_required
@require_POST
def delete(request, uc_id):
    uc = get_object_or_404(UseCaseSpecification, id=uc_id, user=request.user)
    uc.delete()
    messages.success(request, "Caso de uso eliminado.")
    return redirect("modeling:list")


@login_required
def download_diagram(request, uc_id, format):
    """Solo codigo guardado del propietario; no acepta UML libre ni rutas."""
    if not isinstance(format, str) or format not in plantuml.FORMATS:
        return HttpResponse("Formato no permitido.", status=400)
    uc = get_object_or_404(UseCaseSpecification, id=uc_id, user=request.user)
    try: result = plantuml.render(uc.plantuml_code, format)
    except plantuml.PlantUMLError as e:
        return fail(str(e), status=e.status, error=e.code)
    if result.engine != "plantuml":
        return fail("La descarga requiere el motor PlantUML real.", status=503)
    response = HttpResponse(result.data, content_type=result.content_type)
    response["Content-Disposition"] = f'attachment; filename="IngeniaLab_{uc.id}.{format}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Diagram-Cache"] = "HIT" if result.cached else "MISS"
    response["X-Diagram-Duration-Ms"] = str(result.duration_ms)
    response["X-Diagram-Total-Duration-Ms"] = str(result.total_duration_ms)
    return response


# Lecciones guiadas de casos de uso (CU-02, estilo Duolingo).

@login_required
def lesson_list(request):
    attempts = _finished_attempts(request.user)
    if not attempts.exists():
        messages.warning(request, "Para las lecciones primero completa una entrevista y clasifica sus requisitos.")
        return redirect("modeling:list")
    selected = attempts.first()
    if request.GET.get("attempt"):
        try:
            selected = get_object_or_404(attempts, id=request.GET["attempt"])
        except ValidationError:
            return HttpResponse("La entrevista seleccionada no es válida.", status=400)
    mine = list(UseCaseLesson.objects.filter(user=request.user, attempt=selected))
    cards = []
    for ref in ReferenceUseCase.objects.filter(version=selected.version):
        lessons = [lesson for lesson in mine if lesson.reference_id == ref.id]
        completed = [lesson for lesson in lessons if lesson.status == UseCaseLesson.COMPLETED]
        cards.append({
            "ref": ref, **lesson_engine.lesson_status(selected, ref),
            "current": next((lesson for lesson in lessons if lesson.status == UseCaseLesson.IN_PROGRESS), None),
            "completed": completed[0] if completed else None,
            "best_xp": max((lesson.xp for lesson in completed), default=None),
        })
    return render(request, "modeling/lessons.html", {"attempts": attempts, "selected": selected, "cards": cards,
                                                     "lives": lesson_engine.LIVES})


@login_required
@require_POST
def lesson_start(request, ref_id):
    ref = get_object_or_404(ReferenceUseCase, id=ref_id)
    try:
        attempt = get_object_or_404(_finished_attempts(request.user), id=request.POST.get("attempt"),
                                    version_id=ref.version_id)
    except ValidationError:
        return HttpResponse("La entrevista seleccionada no es válida.", status=400)
    try:
        lesson = lesson_engine.start(request.user, attempt, ref)
    except lesson_engine.LessonError as e:
        messages.error(request, str(e))
        return redirect(f"{reverse('modeling:lessons')}?attempt={attempt.id}")
    return redirect("modeling:lesson", lesson_id=lesson.id)


@login_required
def lesson_view(request, lesson_id):
    lesson = get_object_or_404(UseCaseLesson.objects.select_related("reference", "attempt"),
                               id=lesson_id, user=request.user)
    return render(request, "modeling/lesson.html", {"lesson": lesson, "state": lesson_engine.state(lesson)})


@require_POST
def api_lesson_answer(request, lesson_id):
    lesson = get_object_or_404(UseCaseLesson, id=lesson_id, user=request.user)
    data = read_json(request)
    try:
        result = lesson_engine.answer(lesson, data.get("exercise_id"), data.get("answer"))
    except lesson_engine.LessonError as e:
        return fail(str(e))
    return ok(**result)


@require_POST
def api_lesson_save(request, lesson_id):
    """Genera el diagrama del caso de uso construido en la lección y lo guarda una sola vez (CU-02)."""
    with transaction.atomic():
        lesson = get_object_or_404(
            UseCaseLesson.objects.select_for_update().select_related("reference", "attempt"),
            id=lesson_id, user=request.user)
        if lesson.status != UseCaseLesson.COMPLETED:
            return fail("Termina la lección para guardar su caso de uso.")
        if lesson.use_case_id:
            uc = UseCaseSpecification.objects.select_related("diagram").get(id=lesson.use_case_id)
            return ok(id=str(uc.id), svg=uc.diagram.svg, engine=uc.diagram.engine, saved_before=True,
                      edit_url=reverse("modeling:edit", args=[uc.id]), badges=[])
        form = UseCaseForm(data={**lesson.reference.spec, "attempt_id": str(lesson.attempt_id)}, user=request.user)
        if not form.is_valid():
            return fail(validators.REQUIRED_MESSAGE, errors=form.error_messages())
        spec = form.cleaned_data
        code = build_usecase_diagram(spec)
        try:
            result = plantuml.render(code)
        except plantuml.PlantUMLError as e:
            return fail(str(e), status=e.status, error=e.code)
        uc = UseCaseSpecification.objects.create(
            user=request.user, attempt=lesson.attempt, name=spec["name"], system_name=spec["system_name"],
            actors={"primary": spec["primary_actors"], "secondary": spec["secondary_actors"]},
            preconditions=spec["preconditions"], main_flow=spec["main_flow"],
            alternate_flows=spec["alternate_flows"], postconditions=spec["postconditions"],
            relations=spec["relations"], plantuml_code=code,
        )
        GeneratedDiagram.objects.create(use_case=uc, code_hash=result.code_hash, svg=result.svg, engine=result.engine)
        lesson.use_case = uc
        lesson.save(update_fields=["use_case"])
    return ok(id=str(uc.id), svg=result.svg, engine=result.engine, saved_before=False,
              edit_url=reverse("modeling:edit", args=[uc.id]), badges=evaluate_badges(request.user))


@login_required
def wizard(request):
    """Asistente paso a paso para crear un caso de uso propio (CU-02); usa las mismas API que el editor."""
    attempts = _finished_attempts(request.user)
    if not attempts.exists():
        messages.warning(request, "Para modelar casos de uso primero completa al menos una entrevista en el módulo de Elicitación.")
        return redirect("modeling:list")
    guide = _guide(attempts)
    # De los casos de uso de referencia del escenario salen las sugerencias de actores y qué requisitos son
    # parte de otro caso de uso (todos menos el primero de cada referencia, que es la meta del usuario).
    actors, part_of = {}, {}
    references = list(ReferenceUseCase.objects.filter(version__in={a.version_id for a in attempts}))
    for ref in references:
        actors.setdefault(ref.version_id, set()).update(ref.spec["primary_actors"] + ref.spec["secondary_actors"])
        part_of.setdefault(ref.version_id, set()).update(ref.requirement_keys[1:])
    for item, attempt in zip(guide, attempts):
        item["actors"] = sorted(actors.get(attempt.version_id, ()))
        item["part_of"] = sorted(part_of.get(attempt.version_id, ()))
        # A qué meta pertenece cada regla, para avisar si se mezcla con la meta de otro caso de uso.
        item["rule_of"] = {k: ref.requirement_keys[0] for ref in references
                           if ref.version_id == attempt.version_id for k in ref.requirement_keys[1:]}
        # Metas con caso de uso de referencia: el asistente pasa al modo guiado (lección con opciones).
        item["goals"] = {
            ref.requirement_keys[0]: {"start_url": reverse("modeling:lesson_start", args=[ref.id]),
                                      **lesson_engine.lesson_status(attempt, ref)}
            for ref in references if ref.version_id == attempt.version_id
        }
    selected = request.GET.get("attempt", "")
    return render(request, "modeling/wizard.html", {
        "guide": guide, "validation_rules": validators.RULES,
        "selected": selected if any(g["id"] == selected for g in guide) else guide[0]["id"],
    })

