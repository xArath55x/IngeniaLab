import uuid

from django.conf import settings
from django.db import models


class ScenarioVersion(models.Model):
    """Escenario didáctico versionado (scenarios_version, SDS §4.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario_code = models.CharField(max_length=50)
    version_number = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    client_name = models.CharField(max_length=120)
    client_role = models.CharField(max_length=160)
    client_greeting = models.TextField()

    class Meta:
        db_table = "scenarios_version"
        unique_together = ("scenario_code", "version_number")
        ordering = ["scenario_code"]

    def __str__(self):
        return f"{self.scenario_code} v{self.version_number}"

    @property
    def client_initials(self):
        # Omite títulos como «Lic.» o «Sr.» para el avatar.
        words = [w for w in self.client_name.split() if not w.endswith(".")]
        return "".join(w[0] for w in words[:2]).upper()


class InterviewQuestion(models.Model):
    """Pregunta preconfigurada. Cada ronda ofrece tres opciones: muy útil, algo útil y sin aporte."""

    HIGH, MEDIUM, LOW = "high", "medium", "low"
    QUALITIES = [(HIGH, "Muy útil"), (MEDIUM, "Algo útil"), (LOW, "No aporta")]
    POINTS = {HIGH: 10, MEDIUM: 5, LOW: 0}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(ScenarioVersion, on_delete=models.CASCADE, related_name="questions")
    round_number = models.PositiveIntegerField(default=0)
    topic = models.CharField(max_length=80)
    text = models.CharField(max_length=300)
    # Lista de segmentos: [{"text": "...", "req": "<key>" | null}]
    answer_segments = models.JSONField()
    quality = models.CharField(max_length=10, choices=QUALITIES, default=LOW)
    rationale = models.TextField(blank=True, help_text="Por qué la pregunta aporta (o no) a la entrevista")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["round_number", "order"]

    def __str__(self):
        return self.text

    @property
    def points(self):
        return self.POINTS[self.quality]

    @property
    def answer_text(self):
        return " ".join(s["text"] for s in self.answer_segments)


class MasterRequirement(models.Model):
    """Declaración del cliente con su categoría correcta (master_requirements, SDS §4.1)."""

    RF, RNF = "RF", "RNF"
    TYPES = [(RF, "Requisito Funcional"), (RNF, "Requisito No Funcional")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(ScenarioVersion, on_delete=models.CASCADE, related_name="requirements")
    question = models.ForeignKey(InterviewQuestion, on_delete=models.CASCADE, related_name="requirements")
    key = models.CharField(max_length=20)
    statement_text = models.TextField()
    expected_type = models.CharField(max_length=3, choices=TYPES)
    feedback_explanation = models.TextField()
    hint = models.TextField(blank=True)

    class Meta:
        db_table = "master_requirements"
        unique_together = ("version", "key")
        constraints = [
            models.CheckConstraint(condition=models.Q(expected_type__in=["RF", "RNF"]), name="master_req_type_valid"),
        ]

    def __str__(self):
        return f"{self.key}: {self.statement_text[:60]}"


class StudentAttempt(models.Model):
    """Práctica de elicitación + clasificación de un estudiante sobre un escenario."""

    INTERVIEWING, CLASSIFYING = "interviewing", "classifying"
    STATUSES = [(INTERVIEWING, "Entrevista en curso"), (CLASSIFYING, "Clasificación de requisitos")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    version = models.ForeignKey(ScenarioVersion, on_delete=models.PROTECT, related_name="attempts")
    status = models.CharField(max_length=20, choices=STATUSES, default=INTERVIEWING)
    started_at = models.DateTimeField(auto_now_add=True)
    interview_finished_at = models.DateTimeField(null=True, blank=True)
    premature_finish = models.BooleanField(default=False)
    interview_score = models.IntegerField(default=0)
    classification_score = models.IntegerField(default=0)
    classification_precision = models.FloatField(default=0.0)
    hints_used = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.user} · {self.version}"

    @property
    def total_score(self):
        return self.interview_score + self.classification_score

    @property
    def short_id(self):
        return str(self.id)[:8].upper()


class InterviewLogEntry(models.Model):
    """Registro de la bitácora de sesión: una pregunta formulada y su respuesta."""

    attempt = models.ForeignKey(StudentAttempt, on_delete=models.CASCADE, related_name="log_entries")
    question = models.ForeignKey(InterviewQuestion, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    # Snapshot de lo realmente mostrado; no volver a consultar IA al reabrir.
    response_segments = models.JSONField(default=list, blank=True)
    response_source = models.CharField(max_length=10, default="catalog")
    fallback_reason = models.CharField(max_length=32, blank=True, default="")

    @property
    def answer_text(self):
        return " ".join(s["text"] for s in (self.response_segments or self.question.answer_segments))


    class Meta:
        ordering = ["created_at", "id"]
        unique_together = ("attempt", "question")
