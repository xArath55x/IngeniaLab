import uuid

from django.db import models

from apps.interviews.models import MasterRequirement, StudentAttempt


class StudentClassification(models.Model):
    """Clasificación RF/RNF confirmada por el estudiante (student_classifications, SDS §4.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(StudentAttempt, on_delete=models.CASCADE, related_name="classifications")
    master_requirement = models.ForeignKey(MasterRequirement, on_delete=models.CASCADE)
    selected_category = models.CharField(max_length=3, choices=MasterRequirement.TYPES)
    is_correct = models.BooleanField()
    times_changed = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "student_classifications"
        ordering = ["updated_at"]
        constraints = [
            # Evita duplicidad al reclasificar (SDS §4.1).
            models.UniqueConstraint(fields=["attempt", "master_requirement"], name="unique_classification_per_attempt"),
            models.CheckConstraint(condition=models.Q(selected_category__in=["RF", "RNF"]), name="classification_type_valid"),
        ]

class RequirementClassification(models.Model):
    REQUIREMENT_TYPES = [
        ('RF', 'Requisito Funcional'),
        ('RNF', 'Requisito No Funcional'),
    ]
 
 
    attempt = models.ForeignKey(StudentAttempt, on_delete=models.CASCADE, related_name='requirement_classifications')
    
    text_fragment = models.TextField(help_text="Fragmento de texto resaltado de la bitácora.")
    req_type = models.CharField(max_length=3, choices=REQUIREMENT_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'text_fragment'], 
                name='unique_requirement_fragment'
            )
        ]

    def __str__(self):
        return f"[{self.req_type}] {self.text_fragment[:30]}..."
