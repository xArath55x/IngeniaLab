from django.urls import path

from . import views

app_name = "progress"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("partida/nueva/", views.partida_start, name="partida_start"),
    path("partida/continuar/", views.partida_continue, name="partida_continue"),
    path("partida/abandonar/", views.partida_abandon, name="partida_abandon"),
    path("reportes/", views.report_summary, name="reports"),
    path("reportes/descargar/", views.report_download, name="report_download"),
    path("autoguardado/<str:module>/<str:key>/descartar/", views.checkpoint_discard, name="checkpoint_discard_html"),
    path("api/checkpoints/", views.api_checkpoint_save, name="checkpoint_save"),
    path("api/checkpoints/<str:module>/<str:key>/", views.api_checkpoint_get, name="checkpoint_get"),
    path("api/checkpoints/<str:module>/<str:key>/descartar/", views.api_checkpoint_discard, name="checkpoint_discard"),
]
