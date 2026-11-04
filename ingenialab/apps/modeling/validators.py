"""Reglas compartidas de ACT-207A / RF-04. Sin inferencia semántica del texto."""
import re
import unicodedata
from django.core.exceptions import ValidationError

REQUIRED_MESSAGE = "Revisa la plantilla: debe contener un actor principal, pre/poscondiciones y los pasos del flujo básico."
INFINITIVE = re.compile(r"^[a-záéíóúñ]+(?:ar|er|ir)(?:se)?\b", re.IGNORECASE)
# Se publican también al navegador desde la vista: una sola fuente de límites.
RULES = {
    "name": 200, "system_name": 200, "actor": 120,
    "conditions": 4000, "step": 1000, "alternate": 2000,
    "max_actors": 10, "min_steps": 2, "max_steps": 50,
    "max_alternates": 20, "max_relations": 20,
}

def text(value, *, multiline=False):
    if not isinstance(value, str):
        raise ValidationError("Debe ser texto.")
    value = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs") and c not in "\n\t" for c in value):
        raise ValidationError("El texto contiene caracteres de control no permitidos.")
    if multiline:
        return "\n".join(line.strip() for line in value.split("\n")).strip()
    return " ".join(value.split())

def key(value):
    # Comparación de caja equivalente en Python y JavaScript tras NFKC.
    return value.upper().lower()

def structural_errors(spec):
    errors = {}
    primary, secondary = spec.get("primary_actors", []), spec.get("secondary_actors", [])
    for field, values in (("primary_actors", primary), ("secondary_actors", secondary)):
        if len({key(v) for v in values}) != len(values):
            errors[field] = "Hay actores repetidos en la lista."
    if {key(v) for v in primary} & {key(v) for v in secondary}:
        errors["secondary_actors"] = "Un actor no puede ser principal y secundario a la vez."
    seen = set()
    for relation in spec.get("relations", []):
        identity = key(relation["target"])
        if identity == key(spec.get("name", "")):
            errors["relations"] = "Un caso de uso no puede incluirse o extenderse a sí mismo."
        elif identity in seen:
            errors["relations"] = "Hay destinos de relación repetidos."
        seen.add(identity)
    return errors

def suggestions(spec):
    warnings = []
    if spec.get("name") and not INFINITIVE.match(spec["name"]):
        warnings.append("Buena práctica: nombra el caso de uso con un verbo en infinitivo (p. ej. «Registrar préstamo»).")
    if not spec.get("alternate_flows"):
        warnings.append("Considera documentar al menos un flujo alterno o de excepción.")
    if spec.get("main_flow") and spec.get("primary_actors"):
        flow = key(" ".join(spec["main_flow"]))
        if not any(key(a) in flow for a in spec["primary_actors"]):
            warnings.append("Consistencia: el flujo principal no menciona a ningún actor principal.")
    return warnings

# Compatibilidad con consumidores de la interfaz original. Los endpoints usan
# UseCaseForm directamente para no perder errores de tipo ni filas vacías.
def normalize(data):
    from .forms import UseCaseForm
    form = UseCaseForm(data=data)
    form.is_valid()
    return form.cleaned_data

def validate(spec):
    from .forms import UseCaseForm
    form = UseCaseForm(data=spec)
    form.is_valid()
    return form.error_messages(), suggestions(form.cleaned_data)
