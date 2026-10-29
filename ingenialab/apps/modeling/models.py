import uuid

from django.conf import settings
from django.db import models

from apps.interviews.models import ScenarioVersion, StudentAttempt


class UseCaseSpecification(models.Model):
    """Caso de uso estructurado por el estudiante (usecase_specifications, SDS §4.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="use_cases")
    attempt = models.ForeignKey(StudentAttempt, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="use_cases", help_text="Entrevista que sirve de guía")
    name = models.CharField(max_length=200)
    system_name = models.CharField(max_length=200, default="Sistema")
    # {"primary": [...], "secondary": [...]}
    actors = models.JSONField()
    preconditions = models.TextField()
    main_flow = models.JSONField()  # ["paso 1", "paso 2", ...]
    alternate_flows = models.JSONField(default=list)  # ["FA-1 ...", ...]
    postconditions = models.TextField()
    # [{"type": "include"|"extend", "target": "nombre CU"}]
    relations = models.JSONField(default=list)
    plantuml_code = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "usecase_specifications"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    def as_form_data(self):
        return {
            "name": self.name,
            "system_name": self.system_name,
            "primary_actors": self.actors.get("primary", []),
            "secondary_actors": self.actors.get("secondary", []),
            "preconditions": self.preconditions,
            "main_flow": self.main_flow,
            "alternate_flows": self.alternate_flows,
            "postconditions": self.postconditions,
            "relations": self.relations,
            "attempt_id": str(self.attempt_id) if self.attempt_id else "",
        }


class GeneratedDiagram(models.Model):
    """Diagrama renderizado asociado 1:1 a la especificación."""

    use_case = models.OneToOneField(UseCaseSpecification, on_delete=models.CASCADE, related_name="diagram")
    code_hash = models.CharField(max_length=64)
    svg = models.TextField()
    engine = models.CharField(max_length=20)
    generated_at = models.DateTimeField(auto_now=True)


class ReferenceUseCase(models.Model):
    """Caso de uso de referencia de un escenario (data/usecases.json) para las lecciones guiadas de CU-02.

    requirement_keys enlaza con los requisitos (MasterRequirement.key) que el estudiante debe descubrir
    y clasificar como RF para desbloquear la lección. spec tiene el formato de UseCaseForm.
    """

    version = models.ForeignKey(ScenarioVersion, on_delete=models.CASCADE, related_name="reference_use_cases")
    key = models.CharField(max_length=20)
    order = models.PositiveIntegerField(default=0)
    requirement_keys = models.JSONField()
    spec = models.JSONField()
    # Opciones incorrectas y explicación de cada ejercicio de la lección.
    exercises = models.JSONField()

    class Meta:
        db_table = "reference_use_cases"
        ordering = ["version", "order"]
        unique_together = ("version", "key")

    def __str__(self):
        return f"{self.key} · {self.spec['name']}"


class UseCaseLesson(models.Model):
    """Lección tipo Duolingo que construye un caso de uso de referencia ejercicio por ejercicio.

    exercises es una copia con las respuestas (solo servidor); queue lleva los ids pendientes y los
    ejercicios fallados se repiten al final. Con 0 vidas la lección falla y se reinicia desde cero.
    """

    IN_PROGRESS, COMPLETED, FAILED = "in_progress", "completed", "failed"
    STATUSES = [(IN_PROGRESS, "En curso"), (COMPLETED, "Completada"), (FAILED, "Sin vidas")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lessons")
    attempt = models.ForeignKey(StudentAttempt, on_delete=models.CASCADE, related_name="lessons")
    reference = models.ForeignKey(ReferenceUseCase, on_delete=models.CASCADE, related_name="lessons")
    exercises = models.JSONField()
    queue = models.JSONField()
    solved = models.JSONField(default=list)
    lives = models.PositiveSmallIntegerField(default=3)
    mistakes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUSES, default=IN_PROGRESS)
    xp = models.PositiveIntegerField(default=0)
    # Caso de uso guardado al terminar la lección; evita guardarlo dos veces.
    use_case = models.ForeignKey(UseCaseSpecification, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="lessons")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "usecase_lessons"
        ordering = ["-started_at"]
