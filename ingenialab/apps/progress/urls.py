from django.urls import path

from . import views

app_name = "progress"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("partida/nueva/", views.partida_start, name="partida_start"),
    path("partida/continuar/", views.partida_continue, name="partida_continue"),
    path("partida/abandonar/", views.partida_abandon, name="partida_abandon"),
    path("practicas/<str:module>/<uuid:practice_id>/eliminar/", views.practice_dismiss, name="practice_dismiss"),
    path("reportes/", views.report_summary, name="reports"),
    path("reportes/descargar/", views.report_download, name="report_download"),
    path("reportes/enviar/", views.report_submit, name="report_submit"),
    path("reportes/partida/<uuid:partida_id>/", views.report_summary, name="partida_report"),
    path("reportes/partida/<uuid:partida_id>/descargar/", views.report_download, name="partida_report_download"),
    path("reportes/partida/<uuid:partida_id>/enviar/", views.report_submit, name="partida_report_submit"),
    path("profesor/", views.teacher_inbox, name="teacher_inbox"),
    path("seguimiento/<uuid:pk>/", views.submission_detail, name="submission_detail"),
    path("seguimiento/<uuid:pk>/descargar/", views.submission_download, name="submission_download"),
    path("seguimiento/<uuid:pk>/retroalimentacion/", views.submission_feedback, name="submission_feedback"),
    path("autoguardado/<str:module>/<str:key>/descartar/", views.checkpoint_discard, name="checkpoint_discard_html"),
    path("api/checkpoints/", views.api_checkpoint_save, name="checkpoint_save"),
    path("api/checkpoints/<str:module>/<str:key>/", views.api_checkpoint_get, name="checkpoint_get"),
    path("api/checkpoints/<str:module>/<str:key>/descartar/", views.api_checkpoint_discard, name="checkpoint_discard"),
]
