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
