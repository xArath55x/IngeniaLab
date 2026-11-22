import uuid

from django.conf import settings
from django.db import models


class UserBadge(models.Model):
    """Insignia formativa otorgada (sin carácter de calificación oficial)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges")
    code = models.CharField(max_length=40)
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "code")
        ordering = ["awarded_at"]


class ReportExport(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    report_id = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)


class ReportSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    export = models.OneToOneField(ReportExport, on_delete=models.CASCADE, related_name="submission")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_reports")
    points = models.PositiveIntegerField()
    pdf = models.BinaryField()


class ReportFeedback(models.Model):
    submission = models.ForeignKey(ReportSubmission, on_delete=models.CASCADE, related_name="feedback")
    comment = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class PracticeCheckpoint(models.Model):
    """Punto de guardado de una práctica en curso (CU-10, SDS v3.0 §9).

    Conserva solo lo que todavía no tiene registro propio (campos sin guardar, selección en pantalla).
    Nunca se usa para calificar: puntos, pistas y vidas se leen de sus propias tablas (RN-02).
    """

    INTERVIEW, CLASSIFICATION, MODELING, INSPECTION, LESSON = (
        "interview", "classification", "modeling", "inspection", "lesson")
    MODULES = [
        (INTERVIEW, "Entrevista"), (CLASSIFICATION, "Clasificación"), (MODELING, "Caso de uso"),
        (INSPECTION, "Inspección"), (LESSON, "Lección guiada"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="checkpoints")
    module = models.CharField(max_length=20, choices=MODULES)
    key = models.CharField(max_length=64)
    payload = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    paused = models.BooleanField(default=False)
    title = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "practice_checkpoints"
        ordering = ["-updated_at"]
        unique_together = ("user", "module", "key")
        indexes = [models.Index(fields=["user", "updated_at"])]

    def __str__(self):
        return f"{self.user} · {self.get_module_display()} · {self.key} (rev. {self.revision})"


class DismissedPractice(models.Model):
    """Práctica que el alumno quitó de la lista de pendientes del tablero."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    module = models.CharField(max_length=20, choices=PracticeCheckpoint.MODULES)
    practice_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "module", "practice_id"], name="unique_dismissed_practice"),
        ]


class Partida(models.Model):
    """Recorrido completo de un escenario: Entrevista → Clasificación → Modelado → Inspección.

    Cada etapa terminada queda como checkpoint (`checkpoints`: etapa → fecha), y `stage` y `percent` guardan
    dónde va el alumno para que «Continuar partida» lo devuelva ahí. Las respuestas de cada etapa ya se guardan
    en sus propios modelos; la partida solo las une. Solo puede haber una partida en curso por alumno.
    """

    INTERVIEW, CLASSIFICATION, MODELING, INSPECTION, DONE = (
        "interview", "classification", "modeling", "inspection", "done")
    STAGES = [(INTERVIEW, "Entrevista"), (CLASSIFICATION, "Clasificación"), (MODELING, "Modelado"),
              (INSPECTION, "Inspección"), (DONE, "Terminada")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="partidas")
    attempt = models.OneToOneField("interviews.StudentAttempt", on_delete=models.CASCADE, related_name="partida")
    inspection = models.OneToOneField("inspection.InspectionAttempt", on_delete=models.SET_NULL, null=True,
                                      blank=True, related_name="partida")
    stage = models.CharField(max_length=20, choices=STAGES, default=INTERVIEW)
    percent = models.PositiveSmallIntegerField(default=0)
    checkpoints = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    abandoned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(fields=["user"], name="una_partida_en_curso_por_alumno",
                                    condition=models.Q(finished_at__isnull=True, abandoned_at__isnull=True)),
        ]

    def __str__(self):
        return f"{self.user} · {self.attempt.version.title} · {self.get_stage_display()}"

    @property
    def in_progress(self):
        return self.finished_at is None and self.abandoned_at is None
