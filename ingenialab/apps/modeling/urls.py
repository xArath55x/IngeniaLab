from django.urls import path

from . import views

app_name = "modeling"

urlpatterns = [
    path("", views.usecase_list, name="list"),
    path("nuevo/", views.editor, name="new"),
    path("<uuid:uc_id>/", views.editor, name="edit"),
    path("<uuid:uc_id>/diagrama/<str:format>/", views.download_diagram, name="download_diagram"),
    path("<uuid:uc_id>/eliminar/", views.delete, name="delete"),
    path("api/validar/", views.api_validate, name="api_validate"),
    path("api/generar/", views.api_generate, name="api_generate"),
    path("api/guardar/", views.api_save, name="api_save"),
    path("lecciones/", views.lesson_list, name="lessons"),
    path("lecciones/<int:ref_id>/iniciar/", views.lesson_start, name="lesson_start"),
    path("leccion/<uuid:lesson_id>/", views.lesson_view, name="lesson"),
    path("api/leccion/<uuid:lesson_id>/responder/", views.api_lesson_answer, name="api_lesson_answer"),
    path("api/leccion/<uuid:lesson_id>/guardar/", views.api_lesson_save, name="api_lesson_save"),
]
