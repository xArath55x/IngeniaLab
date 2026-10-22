import base64
import json
import uuid

from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.api import fail, ok
from apps.interviews.models import StudentAttempt
from apps.progress.services import evaluate_badges
from integrations.plantuml import service as plantuml
from integrations.plantuml.builder import build_usecase_diagram

from . import validators
from .models import GeneratedDiagram, UseCaseSpecification
from .forms import UseCaseForm


def _finished_attempts(user):
    return user.attempts.filter(status=StudentAttempt.CLASSIFYING).select_related("version")


@login_required
def usecase_list(request):
    return render(request, "modeling/list.html", {
        "use_cases": request.user.use_cases.select_related("attempt__version"),
        "can_model": _finished_attempts(request.user).exists(),
    })


@login_required
def editor(request, uc_id=None):
    attempts = _finished_attempts(request.user)
    if not attempts.exists():
        # Precondición CU-02: al menos una entrevista completada.
        messages.warning(request, "Para modelar casos de uso primero completa al menos una entrevista en el módulo de Elicitación.")
        return redirect("modeling:list")
    uc = get_object_or_404(UseCaseSpecification, id=uc_id, user=request.user) if uc_id else None
    reference = uc.attempt if uc and uc.attempt_id else attempts.first()
    if not uc and request.GET.get("attempt"):
        try:
            reference = get_object_or_404(attempts, id=request.GET["attempt"])
        except ValidationError:
            return HttpResponse("La entrevista seleccionada no es válida.", status=400)
    guide = []
    for a in attempts:
        guide.append({
            "id": str(a.id),
            "label": f"{a.version.title} ({a.started_at:%d/%m/%Y})",
            "system": a.version.title,
            "requirements": [
                {"statement": c.master_requirement.statement_text, "category": c.selected_category}
                for c in a.classifications.select_related("master_requirement")
            ],
        })
    return render(request, "modeling/editor.html", {
        "uc": uc,
        "form_data": uc.as_form_data() if uc else None,
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
    if format not in plantuml.FORMATS:
        return fail("Formato permitido: svg o png.")
    try:
        result = plantuml.render(code, format)
        svg = result.svg if format == "svg" else plantuml.render(code, "svg").svg
    except plantuml.PlantUMLError as e:
        return fail(str(e), status=e.status, error=e.code)
    return ok(plantuml_code=code, svg=svg, engine=result.engine, cached=result.cached,
              spec=spec, warnings=validators.suggestions(spec), code_hash=result.code_hash,
              duration_ms=result.duration_ms, cache_warning=result.warning, image_format=format,
              png_data_uri="data:image/png;base64,"+base64.b64encode(result.data).decode("ascii") if format=="png" else "")



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
    if format not in plantuml.FORMATS:
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
    return response
