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
