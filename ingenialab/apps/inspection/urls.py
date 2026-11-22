from django.urls import path

from . import views

app_name = "inspection"

urlpatterns = [
    path("", views.exercise_list, name="list"),
    path("iniciar/<uuid:exercise_id>/", views.start, name="start"),
    path("intento/<uuid:attempt_id>/", views.inspect, name="inspect"),
    path("intento/<uuid:attempt_id>/responder/<uuid:fragment_id>/", views.guided_answer, name="answer"),
    path("intento/<uuid:attempt_id>/revision/<uuid:fragment_id>/", views.inspect, name="review"),
    path("intento/<uuid:attempt_id>/terminar/", views.guided_finish, name="finish"),
    path("api/intento/<uuid:attempt_id>/hallazgo/", views.api_finding, name="api_finding"),
    path("api/intento/<uuid:attempt_id>/pista/", views.api_hint, name="api_hint"),
    path("api/intento/<uuid:attempt_id>/concluir/", views.api_conclude, name="api_conclude"),
]
