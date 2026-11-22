from django.conf import settings
from django.db import models


class AccountRole(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Alumno"
        TEACHER = "teacher", "Profesor"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_role")
    role = models.CharField(max_length=7, choices=Role.choices)


def is_teacher(user):
    profile = getattr(user, "account_role", None)
    return profile is not None and profile.role == AccountRole.Role.TEACHER
