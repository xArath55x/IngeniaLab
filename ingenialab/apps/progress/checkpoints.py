"""Autoguardado y reanudación de prácticas (CU-10, RF-10; SDS v3.0 §9).

Un punto de guardado conserva lo que aún no tiene registro propio: los campos de un caso de uso
sin guardar o la selección en pantalla. Las respuestas confirmadas (preguntas, clasificaciones,
hallazgos, respuestas de lección) ya se guardan en cada acción y no pasan por aquí.

Reglas:
- Solo el dueño de la práctica puede guardar, consultar o descartar (recurso ajeno → 404).
- Bloqueo optimista con `revision`: el cliente envía la revisión que conoce (0 si no tiene) y,
  si no coincide con la guardada, se responde 409 sin escribir (FE-2: otra pestaña).
- Una práctica cerrada ya no acepta puntos de guardado y el suyo se borra (RN-01).
- El payload nunca se usa para calificar (RN-02).
- `purge` borra los puntos sin cambios en N días (RN-03).
"""
import json
import re
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PracticeCheckpoint

SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 64 * 1024
NEW_USE_CASE_PREFIX = "nuevo:"
PURGE_DAYS = 90
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class CheckpointError(Exception):
    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra

    def as_json(self):
        return {"ok": False, "error": self.code, "message": self.message, **self.extra}


def _not_found():
    return CheckpointError("not_found", "No se encontró esa práctica.", status=404)


# Módulo del punto de guardado → módulo de INGENIALAB_MODULES que lo atiende (ModuleGateMiddleware).
APP_MODULE = {
    PracticeCheckpoint.INTERVIEW: "interviews", PracticeCheckpoint.CLASSIFICATION: "classification",
    PracticeCheckpoint.MODELING: "modeling", PracticeCheckpoint.LESSON: "modeling",
    PracticeCheckpoint.INSPECTION: "inspection",
}


def enabled_modules():
    """Módulos de punto de guardado cuyo módulo de la aplicación está habilitado."""
    return [module for module, app in APP_MODULE.items() if app in settings.INGENIALAB_MODULES]


def validate_key(module, key):
    """Normaliza la clave: UUID de la práctica o, en modelado, `nuevo:<uuid>` para un caso sin guardar."""
    if module not in dict(PracticeCheckpoint.MODULES):
        raise CheckpointError("invalid_module", "El módulo indicado no admite autoguardado.")
    if module not in enabled_modules():
        raise CheckpointError("module_disabled", "Este módulo no está disponible.", status=404)
    key = key.strip().lower() if isinstance(key, str) else ""
    raw = key[len(NEW_USE_CASE_PREFIX):] if module == PracticeCheckpoint.MODELING and key.startswith(NEW_USE_CASE_PREFIX) else key
    if not _UUID.match(raw):
        raise CheckpointError("invalid_key", "La clave de la práctica no es válida.")
    return key


TITLE_MAX = PracticeCheckpoint._meta.get_field("title").max_length
MAX_NEW_DRAFTS = 5


def _title(text):
    """El título se muestra en el tablero; nunca debe exceder la columna (en PostgreSQL sería un 500)."""
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1] + "…"


def practice_state(user, module, key, payload=None):
    """Devuelve (título, abierta) de la práctica del usuario. Si no existe o es ajena, 404."""
    title, is_open = _practice_state(user, module, key, payload)
    return _title(title), is_open


def _practice_state(user, module, key, payload=None):
    from apps.inspection.models import InspectionAttempt
    from apps.interviews.models import StudentAttempt
    from apps.modeling.models import UseCaseLesson, UseCaseSpecification

    draft_name = ""
    if isinstance(payload, dict) and isinstance(payload.get("name"), str):
        draft_name = payload["name"].strip()[:150]
    try:
        if module in (PracticeCheckpoint.INTERVIEW, PracticeCheckpoint.CLASSIFICATION):
            attempt = StudentAttempt.objects.select_related("version").get(id=key, user=user)
            wanted = StudentAttempt.INTERVIEWING if module == PracticeCheckpoint.INTERVIEW else StudentAttempt.CLASSIFYING
            label = "Entrevista" if module == PracticeCheckpoint.INTERVIEW else "Clasificación"
            return f"{label} · {attempt.version.title}", attempt.status == wanted
        if module == PracticeCheckpoint.INSPECTION:
            attempt = InspectionAttempt.objects.select_related("exercise").get(id=key, user=user)
            return f"Inspección · {attempt.exercise.title}", attempt.concluded_at is None
        if module == PracticeCheckpoint.LESSON:
            lesson = UseCaseLesson.objects.select_related("reference").get(id=key, user=user)
            return f"Lección · {lesson.reference.spec['name']}", lesson.status == UseCaseLesson.IN_PROGRESS
        if key.startswith(NEW_USE_CASE_PREFIX):
            return f"Caso de uso · {draft_name or 'nuevo'}", True
        use_case = UseCaseSpecification.objects.get(id=key, user=user)
        return f"Caso de uso · {draft_name or use_case.name}", True
    except (StudentAttempt.DoesNotExist, InspectionAttempt.DoesNotExist, UseCaseLesson.DoesNotExist,
            UseCaseSpecification.DoesNotExist):
        raise _not_found()


def _clean_payload(payload):
    if not isinstance(payload, dict):
        raise CheckpointError("invalid_payload", "El contenido del autoguardado debe ser un objeto JSON.")
    schema = payload.get("schema", SCHEMA_VERSION)
    if schema != SCHEMA_VERSION:
        raise CheckpointError("invalid_payload", "La versión del autoguardado no es compatible; recarga la página.")
    payload = {**payload, "schema": SCHEMA_VERSION}
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise CheckpointError("payload_too_large", "El autoguardado excede 64 KB.", status=413)
    return payload


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CheckpointError("invalid_revision", "La revisión del autoguardado no es válida.")
    return value


def _conflict(current):
    return CheckpointError(
        "revision_conflict",
        "Esta práctica se guardó desde otra pestaña. Recarga la página para continuar con la versión más reciente.",
        status=409, server_revision=current)


def save(user, module, key, revision, payload, pause=False):
    """Crea o actualiza el punto de guardado. `revision` = la que conoce el cliente (0 si ninguna)."""
    key = validate_key(module, key)
    revision = _revision(revision)
    payload = _clean_payload(payload)
    title, is_open = practice_state(user, module, key, payload)
    if not is_open:
        # Fuera de la transacción: el error no debe revertir el borrado (RN-01).
        PracticeCheckpoint.objects.filter(user=user, module=module, key=key).delete()
        raise CheckpointError("practice_closed", "Esta práctica ya terminó; no hace falta guardarla.", status=409)
    with transaction.atomic():
        checkpoint = PracticeCheckpoint.objects.select_for_update().filter(user=user, module=module, key=key).first()
        if checkpoint is None:
            if revision != 0:
                raise _conflict(0)
            if key.startswith(NEW_USE_CASE_PREFIX):
                # Bloquea la fila del usuario: dos pestañas creando borradores a la vez no rebasan el límite.
                get_user_model().objects.select_for_update().filter(pk=user.pk).first()
            if key.startswith(NEW_USE_CASE_PREFIX) and PracticeCheckpoint.objects.filter(
                    user=user, module=module, key__startswith=NEW_USE_CASE_PREFIX).count() >= MAX_NEW_DRAFTS:
                raise CheckpointError(
                    "too_many_drafts",
                    f"Ya tienes {MAX_NEW_DRAFTS} casos de uso sin guardar. Guarda o descarta alguno desde Mi progreso.",
                    status=409)
            try:
                with transaction.atomic():
                    return PracticeCheckpoint.objects.create(
                        user=user, module=module, key=key, payload=payload, paused=bool(pause), title=title)
            except IntegrityError:
                # Otra pestaña lo creó al mismo tiempo.
                raise _conflict(PracticeCheckpoint.objects.get(user=user, module=module, key=key).revision)
        if revision != checkpoint.revision:
            raise _conflict(checkpoint.revision)
        checkpoint.payload, checkpoint.paused, checkpoint.title = payload, bool(pause), title
        checkpoint.revision += 1
        checkpoint.save()
        return checkpoint


def get(user, module, key):
    """Punto de guardado de una práctica del usuario, o None si no hay (o si la práctica ya terminó).

    Una práctica ajena o inexistente es 404. Que no haya punto de guardado es el caso normal al abrir
    una pantalla, así que no es un error.
    """
    key = validate_key(module, key)
    _, is_open = practice_state(user, module, key)
    mine = PracticeCheckpoint.objects.filter(user=user, module=module, key=key)
    if not is_open:
        mine.delete()
        return None
    return mine.first()


def close(user, module, key):
    """Borra el punto de guardado de una práctica que acaba de terminar (RN-01). Lo llaman los servicios al cerrarla."""
    PracticeCheckpoint.objects.filter(user=user, module=module, key=str(key)).delete()


def consume_new_draft(user, key):
    """Borra el borrador `nuevo:<uuid>` de un caso de uso que se acaba de guardar, en la misma transacción.

    Así el borrador no sobrevive aunque el navegador cierre la pestaña antes de descartarlo. Una clave inválida
    se ignora: el guardado del caso de uso no debe fallar por el autoguardado.
    """
    if not isinstance(key, str) or not key.strip().lower().startswith(NEW_USE_CASE_PREFIX):
        return
    try:
        key = validate_key(PracticeCheckpoint.MODELING, key)
    except CheckpointError:
        return
    close(user, PracticeCheckpoint.MODELING, key)


def discard(user, module, key):
    key = validate_key(module, key)
    deleted, _ = PracticeCheckpoint.objects.filter(user=user, module=module, key=key).delete()
    if not deleted:
        practice_state(user, module, key)  # Práctica ajena o inexistente: 404 (not_found), como en get().
        raise CheckpointError("no_checkpoint", "No hay un autoguardado para esta práctica.", status=404)


def purge(days=PURGE_DAYS, now=None):
    """Borra los puntos de guardado sin cambios en `days` días (RN-03). Devuelve cuántos borró."""
    limit = (now or timezone.now()) - timedelta(days=days)
    deleted, _ = PracticeCheckpoint.objects.filter(updated_at__lt=limit).delete()
    return deleted


def serialize(checkpoint, with_payload=False):
    data = {"ok": True, "found": True, "module": checkpoint.module, "key": checkpoint.key, "revision": checkpoint.revision,
            "paused": checkpoint.paused, "saved_at": timezone.localtime(checkpoint.updated_at).isoformat()}
    if with_payload:
        data["payload"] = checkpoint.payload
    return data


def latest_new_draft_key(user, lesson_id=None, attempt_id=None):
    """Clave del borrador de caso de uso nuevo más reciente, para que /modelado/nuevo/ lo retome (no una clave nueva).

    Con `lesson_id` solo vale un borrador de esa lección; con `attempt_id`, uno de esa entrevista que no venga de
    una lección. Así ?leccion= y ?attempt= retoman su propio borrador en vez de dejar uno huérfano en cada visita.
    Sin filtros solo vale un borrador que no venga de una lección: retomarlo copiaría su `lesson_id` y el caso
    nuevo se guardaría como el de esa lección. Hay a lo más MAX_NEW_DRAFTS borradores, así que se filtran aquí y no
    con consultas sobre el JSON.
    """
    drafts = (PracticeCheckpoint.objects.filter(user=user, module=PracticeCheckpoint.MODELING,
                                                key__startswith=NEW_USE_CASE_PREFIX)
              .order_by("-updated_at").values_list("key", "payload"))
    for key, payload in drafts:
        payload = payload if isinstance(payload, dict) else {}
        if lesson_id is not None and str(payload.get("lesson_id") or "") != str(lesson_id):
            continue
        if lesson_id is None and payload.get("lesson_id"):
            continue
        if attempt_id is not None and (payload.get("lesson_id") or str(payload.get("attempt_id") or "") != str(attempt_id)):
            continue
        return key
    return ""


def resume_url(checkpoint):
    """Enlace de reanudación calculado en el servidor a partir de módulo y clave, nunca del payload (SDS §9.5)."""
    from django.urls import reverse

    module, key = checkpoint.module, checkpoint.key
    if module == PracticeCheckpoint.MODELING:
        if key.startswith(NEW_USE_CASE_PREFIX):
            return f"{reverse('modeling:new')}?borrador={key}"
        return reverse("modeling:edit", args=[key])
    names = {PracticeCheckpoint.INTERVIEW: "interviews:interview", PracticeCheckpoint.CLASSIFICATION: "classification:classify",
             PracticeCheckpoint.INSPECTION: "inspection:inspect", PracticeCheckpoint.LESSON: "modeling:lesson"}
    return reverse(names[module], args=[key])


def _open_keys(user, module, keys):
    """Las claves de `keys` cuyas prácticas siguen abiertas, con una sola consulta por módulo."""
    from apps.inspection.models import InspectionAttempt
    from apps.interviews.models import StudentAttempt
    from apps.modeling.models import UseCaseLesson, UseCaseSpecification

    ids = [k for k in keys if not k.startswith(NEW_USE_CASE_PREFIX)]
    if module == PracticeCheckpoint.INTERVIEW:
        found = StudentAttempt.objects.filter(user=user, id__in=ids, status=StudentAttempt.INTERVIEWING)
    elif module == PracticeCheckpoint.CLASSIFICATION:
        found = StudentAttempt.objects.filter(user=user, id__in=ids, status=StudentAttempt.CLASSIFYING)
    elif module == PracticeCheckpoint.INSPECTION:
        found = InspectionAttempt.objects.filter(user=user, id__in=ids, concluded_at__isnull=True)
    elif module == PracticeCheckpoint.LESSON:
        found = UseCaseLesson.objects.filter(user=user, id__in=ids, status=UseCaseLesson.IN_PROGRESS)
    elif module == PracticeCheckpoint.MODELING:
        found = UseCaseSpecification.objects.filter(user=user, id__in=ids)
    else:
        return set()
    open_keys = {str(pk) for pk in found.values_list("id", flat=True)}
    if module == PracticeCheckpoint.MODELING:
        open_keys |= {k for k in keys if k.startswith(NEW_USE_CASE_PREFIX)}
    return open_keys


def for_dashboard(user):
    """Puntos de guardado vigentes del usuario para «Retomar trabajo», del más reciente al más antiguo.

    Devuelve un índice por (módulo, clave) para marcar las prácticas que ya lista el tablero (incluidos los casos
    de uso guardados con cambios autoguardados) y los borradores de casos de uso nuevos, que solo existen como punto
    de guardado. Los servicios borran el punto al cerrar, reiniciar o borrar cada práctica (`close`); aquí solo se
    omiten los que quedaran de prácticas cerradas, sin escribir en la BD en un GET (los borra `purge`, RN-03).
    Tampoco se listan los de módulos deshabilitados en INGENIALAB_MODULES.
    """
    found = list(PracticeCheckpoint.objects.filter(user=user, module__in=enabled_modules()).order_by("-updated_at"))
    keys = defaultdict(list)
    for checkpoint in found:
        keys[checkpoint.module].append(checkpoint.key)
    open_keys = {module: _open_keys(user, module, module_keys) for module, module_keys in keys.items()}
    index, drafts = {}, []
    for checkpoint in found:
        if checkpoint.key not in open_keys[checkpoint.module]:
            continue
        checkpoint.resume_url = resume_url(checkpoint)
        index[(checkpoint.module, checkpoint.key)] = checkpoint
        if checkpoint.module == PracticeCheckpoint.MODELING and checkpoint.key.startswith(NEW_USE_CASE_PREFIX):
            drafts.append(checkpoint)
    return index, drafts
