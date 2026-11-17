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
]
