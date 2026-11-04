from django.contrib import admin

from .models import AnswerVariant, InterviewQuestion, MasterRequirement, ScenarioVersion, StudentAttempt


class QuestionInline(admin.TabularInline):
    model = InterviewQuestion
    extra = 0


@admin.register(ScenarioVersion)
class ScenarioVersionAdmin(admin.ModelAdmin):
    list_display = ("scenario_code", "version_number", "title", "is_active")
    inlines = [QuestionInline]


admin.site.register(MasterRequirement)
admin.site.register(StudentAttempt)


@admin.register(AnswerVariant)
class AnswerVariantAdmin(admin.ModelAdmin):
    """Revisión del banco de respuestas: desmarcar «activa» oculta la variante a los estudiantes."""

    list_display = ("version", "round_number", "quality", "preview", "is_active", "model", "created_at")
    list_display_links = ("preview",)
    list_editable = ("is_active",)
    list_filter = ("version", "quality", "is_active", "round_number")
    readonly_fields = ("version", "round_number", "quality", "question_hash", "segments", "model", "created_at")

    @admin.display(description="Respuesta")
    def preview(self, obj):
        return obj.text[:160]

