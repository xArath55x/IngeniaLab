from django.urls import path

from . import views

app_name = "progress"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reportes/", views.report_summary, name="reports"),
    path("reportes/descargar/", views.report_download, name="report_download"),
    path("api/checkpoints/", views.api_checkpoint_save, name="checkpoint_save"),
    path("api/checkpoints/<str:module>/<str:key>/", views.api_checkpoint_get, name="checkpoint_get"),
    path("api/checkpoints/<str:module>/<str:key>/descartar/", views.api_checkpoint_discard, name="checkpoint_discard"),
]
