"""PlantUML fuera de la transacción al guardar (ACT-313B; revisión del PR #48).

Con SQLite en modo IMMEDIATE, una transacción abierta retiene el bloqueo de escritura de toda la base.
Si el diagrama se generara dentro (~1.5 s en frío), las demás escrituras de la aplicación esperarían.
"""
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import override_settings

from apps.classification.services import available_requirements
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.modeling.views import plantuml
from apps.progress.tests import BaseCase


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class RenderOutsideTransactionTests(BaseCase):
    def completed_lesson(self):
        attempt = self.finished_attempt()
        for req in available_requirements(attempt):
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": req.expected_type})
        ref = ReferenceUseCase.objects.get(version=self.version, key="UC-B1")
        self.client.post(f"/modelado/lecciones/{ref.id}/iniciar/", {"attempt": str(attempt.id)})
        lesson = UseCaseLesson.objects.get()
        by_id = {e["id"]: e for e in lesson.exercises}
        while lesson.status == UseCaseLesson.IN_PROGRESS:
            self.post(f"/modelado/api/leccion/{lesson.id}/responder/",
                      {"exercise_id": lesson.queue[0], "answer": by_id[lesson.queue[0]]["answer"]})
            lesson.refresh_from_db()
        return lesson

    def render_depths(self, call):
        """Ejecuta `call` y devuelve la profundidad de transacciones con que se llamó a PlantUML."""
        baseline, depths, real = len(connection.atomic_blocks), [], plantuml.render

        def spy(*args, **kwargs):
            depths.append(len(connection.atomic_blocks) - baseline)
            return real(*args, **kwargs)

        with patch("apps.modeling.views.plantuml.render", side_effect=spy):
            response = call()
        return response, depths

    def test_lesson_save_renders_outside_transaction(self):
        lesson = self.completed_lesson()
        r, depths = self.render_depths(lambda: self.post(f"/modelado/api/leccion/{lesson.id}/guardar/"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(depths, [0])
        again = self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").json()
        self.assertTrue(again["saved_before"])
        self.assertEqual(self.user.use_cases.count(), 1)

    def test_editor_save_renders_outside_transaction(self):
        lesson = self.completed_lesson()
        spec = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}").context["form_data"]
        r, depths = self.render_depths(lambda: self.post("/modelado/api/guardar/", {**spec, "lesson_id": str(lesson.id)}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(depths, [0])
        lesson.refresh_from_db()
        self.assertIsNotNone(lesson.use_case_id)
