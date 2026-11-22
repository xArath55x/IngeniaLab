from django import forms
from django.contrib.auth import get_user_model
from django.db.models.functions import Lower

from apps.accounts.models import AccountRole


class TeacherChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, teacher):
        name = teacher.get_full_name()
        return f"{name} (@{teacher.username})" if name else f"@{teacher.username}"


class ReportSubmissionForm(forms.Form):
    teacher = TeacherChoiceField(
        label="Profesor",
        queryset=get_user_model().objects.filter(
            is_active=True, account_role__role=AccountRole.Role.TEACHER,
        ).order_by(Lower("username")),
        to_field_name="username",
        empty_label="Selecciona un profesor",
        error_messages={"invalid_choice": "Selecciona un profesor activo de la lista."},
    )

    @property
    def has_teachers(self):
        return self.fields["teacher"].queryset.exists()


class ReportFeedbackForm(forms.Form):
    comment = forms.CharField(label="Retroalimentación", max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))
