"""Formulario estructurado y validación autoritativa de CU-02 (ACT-207A)."""
from django import forms
from django.core.exceptions import ValidationError
from apps.interviews.models import StudentAttempt
from .validators import RULES, structural_errors, text

class NormalizedTextField(forms.CharField):
    def __init__(self, *args, multiline=False, **kwargs):
        self.multiline = multiline
        super().__init__(*args, **kwargs)
    def to_python(self, value):
        return "" if value is None else text(value, multiline=self.multiline)

class TextListField(forms.Field):
    def __init__(self, *, minimum=0, maximum, item_limit, **kwargs):
        self.minimum, self.maximum, self.item_limit = minimum, maximum, item_limit
        super().__init__(required=False, **kwargs)
    def to_python(self, value):
        if value is None: value = []
        if not isinstance(value, list):
            raise ValidationError("Debe ser una lista de textos.")
        if not self.minimum <= len(value) <= self.maximum:
            raise ValidationError(f"Debe contener entre {self.minimum} y {self.maximum} elementos.")
        result = []
        for i, item in enumerate(value, 1):
            try: cleaned = text(item)
            except ValidationError as e: raise ValidationError(f"Elemento {i}: {e.messages[0]}") from e
            if not cleaned:
                raise ValidationError(f"El elemento {i} está vacío: complétalo o elimina la fila.")
            if len(cleaned) > self.item_limit:
                raise ValidationError(f"El elemento {i} admite hasta {self.item_limit} caracteres.")
            result.append(cleaned)
        return result

class RelationsField(forms.Field):
    def __init__(self, **kwargs): super().__init__(required=False, **kwargs)
    def to_python(self, value):
        if value is None: value = []
        if not isinstance(value, list) or len(value) > RULES["max_relations"]:
            raise ValidationError(f"Debe ser una lista de hasta {RULES['max_relations']} relaciones.")
        result = []
        for i, row in enumerate(value, 1):
            if not isinstance(row, dict) or row.get("type") not in ("include", "extend"):
                raise ValidationError(f"Relación {i}: selecciona include o extend.")
            target = text(row.get("target", ""))
            if not target or len(target) > RULES["name"]:
                raise ValidationError(f"Relación {i}: escribe un destino de hasta {RULES['name']} caracteres.")
            result.append({"type": row["type"], "target": target})
        return result

class UseCaseForm(forms.Form):
    name = NormalizedTextField(max_length=RULES["name"], label="Nombre del caso de uso",
                               error_messages={"required": "Escribe el nombre del caso de uso."})
    system_name = NormalizedTextField(max_length=RULES["system_name"], required=False, label="Sistema")
    primary_actors = TextListField(minimum=1, maximum=RULES["max_actors"], item_limit=RULES["actor"], label="Actores principales")
    secondary_actors = TextListField(maximum=RULES["max_actors"], item_limit=RULES["actor"], label="Actores secundarios")
    preconditions = NormalizedTextField(multiline=True, max_length=RULES["conditions"], widget=forms.Textarea,
                                       error_messages={"required": "Indica las precondiciones (Ninguna si no aplica)."})
    main_flow = TextListField(minimum=RULES["min_steps"], maximum=RULES["max_steps"], item_limit=RULES["step"], label="Flujo principal")
    alternate_flows = TextListField(maximum=RULES["max_alternates"], item_limit=RULES["alternate"], label="Flujos alternos")
    postconditions = NormalizedTextField(multiline=True, max_length=RULES["conditions"], widget=forms.Textarea,
                                        error_messages={"required": "Indica el estado final en las postcondiciones."})
    relations = RelationsField()
    attempt_id = forms.UUIDField(required=False, error_messages={"invalid": "La entrevista seleccionada no es válida."})

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_system_name(self):
        return self.cleaned_data["system_name"] or "Sistema"

    def clean_attempt_id(self):
        value = self.cleaned_data["attempt_id"]
        if value and self.user is not None:
            if not StudentAttempt.objects.filter(id=value, user=self.user, status=StudentAttempt.CLASSIFYING).exists():
                raise ValidationError("Selecciona una entrevista finalizada de tu cuenta.")
        return str(value) if value else ""

    def clean(self):
        data = super().clean()
        for field, message in structural_errors(data).items():
            self.add_error(field, message)
        return data

    def error_messages(self):
        return {field: " ".join(messages) for field, messages in self.errors.items()}

    def numbered_steps(self):
        """Contrato de ACT-207A: índice consecutivo derivado, sin cambiar main_flow."""
        return [{"number": i, "text": value} for i, value in enumerate(self.cleaned_data.get("main_flow", []), 1)]
