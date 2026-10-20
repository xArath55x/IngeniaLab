from django.urls import path

from . import views

app_name = "interviews"

urlpatterns = [
    path("", views.scenario_list, name="scenarios"),
    path("iniciar/<uuid:version_id>/", views.start_attempt, name="start"),
    path("intento/<uuid:attempt_id>/", views.interview, name="interview"),
    path("api/intento/<uuid:attempt_id>/preguntar/", views.api_ask, name="api_ask"),
    path("api/intento/<uuid:attempt_id>/finalizar/", views.api_finish, name="api_finish"),
    path("api/intento/<uuid:attempt_id>/reiniciar/", views.api_reset, name="api_reset"),
]
