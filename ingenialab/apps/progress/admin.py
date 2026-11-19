from django.contrib import admin

from .models import PracticeCheckpoint


@admin.register(PracticeCheckpoint)
class PracticeCheckpointAdmin(admin.ModelAdmin):
    list_display = ("user", "module", "title", "revision", "paused", "updated_at")
    list_filter = ("module", "paused")
    search_fields = ("user__username", "title", "key")
    readonly_fields = ("id", "user", "module", "key", "payload", "revision", "updated_at")
