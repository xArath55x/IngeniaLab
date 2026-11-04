"""Tablero «Mi progreso»: retomar trabajo, lecciones guiadas e insignias (RF-06, RF-07)."""
from django.conf import settings
from django.test import override_settings

from apps.classification.services import available_requirements
from apps.interviews.models import StudentAttempt
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.progress.services import BADGES, open_interviews

from .tests import BaseCase


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class DashboardTests(BaseCase):
    def ready_attempt(self):
        attempt = self.finished_attempt()
        for req in available_requirements(attempt):
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": req.expected_type})
        return attempt

    def start_lesson(self, attempt, key="UC-B1"):
        ref = ReferenceUseCase.objects.get(version=self.version, key=key)
        self.client.post(f"/modelado/lecciones/{ref.id}/iniciar/", {"attempt": str(attempt.id)})
        return UseCaseLesson.objects.get(user=self.user, reference=ref, status=UseCaseLesson.IN_PROGRESS)

    def test_open_interviews_grouped_by_scenario_with_progress(self):
        older = self.new_attempt()
        latest = self.new_attempt()
        self.ask_rounds(latest, rounds=2)
        groups = open_interviews(self.user)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["latest"].id, latest.id)
        self.assertEqual([a.id for a in groups[0]["older"]], [older.id])
        r = self.client.get("/")
        self.assertContains(r, "Pregunta 2 de 9")
        self.assertContains(r, "Ver 1 entrevista más")

    def test_discard_open_interview(self):
        attempt = self.new_attempt()
        r = self.client.post(f"/elicitacion/intento/{attempt.id}/descartar/")
        self.assertRedirects(r, "/")
        self.assertFalse(StudentAttempt.objects.filter(id=attempt.id).exists())

    def test_discard_keeps_finished_and_foreign_interviews(self):
        finished = self.finished_attempt()
        self.client.post(f"/elicitacion/intento/{finished.id}/descartar/")
        self.assertTrue(StudentAttempt.objects.filter(id=finished.id).exists())
        foreign = StudentAttempt.objects.create(user=self.other, version=self.version)
        r = self.client.post(f"/elicitacion/intento/{foreign.id}/descartar/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(StudentAttempt.objects.filter(id=foreign.id).exists())

    def test_discard_requires_post(self):
        attempt = self.new_attempt()
        self.assertEqual(self.client.get(f"/elicitacion/intento/{attempt.id}/descartar/").status_code, 405)

    def test_lesson_in_progress_appears_in_resume(self):
        lesson = self.start_lesson(self.ready_attempt())
        r = self.client.get("/")
        self.assertContains(r, "Lección guiada")
        self.assertContains(r, f"/modelado/leccion/{lesson.id}/")
        self.assertContains(r, "Lecciones guiadas completadas: <strong>0 de 8</strong>", html=False)

    def test_guided_badge_for_lesson_without_losing_lives(self):
        lesson = self.start_lesson(self.ready_attempt())
        by_id = {e["id"]: e for e in lesson.exercises}
        while lesson.status == UseCaseLesson.IN_PROGRESS:
            self.post(f"/modelado/api/leccion/{lesson.id}/responder/",
                      {"exercise_id": lesson.queue[0], "answer": by_id[lesson.queue[0]]["answer"]})
            lesson.refresh_from_db()
        self.assertTrue(self.user.badges.filter(code="guided").exists())
        r = self.client.get("/")
        self.assertContains(r, "Lecciones guiadas completadas: <strong>1 de 8</strong>", html=False)

    def test_locked_badges_explain_how_to_earn_them(self):
        r = self.client.get("/")
        self.assertContains(r, BADGES["auditor"][2])
        self.assertNotContains(r, "Bloqueada")
