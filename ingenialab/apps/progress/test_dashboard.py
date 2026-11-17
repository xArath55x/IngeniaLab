"""Tablero «Mi progreso»: retomar trabajo, lecciones guiadas e insignias (RF-06, RF-07)."""
from django.conf import settings
from django.test import override_settings

from apps.classification import services as classification_services
from apps.classification.services import available_requirements
from apps.inspection import services as inspection_services
from apps.inspection.models import InspectionExercise
from apps.interviews.models import InterviewQuestion, ScenarioVersion, StudentAttempt
from apps.modeling import lessons
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.progress.services import BADGES, LEVELS, USE_CASE_POINTS, level_for, open_interviews

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
        total = ReferenceUseCase.objects.filter(version__is_active=True).count()
        self.assertContains(r, f"Lecciones guiadas completadas: <strong>0 de {total}</strong>", html=False)

    def test_guided_badge_for_lesson_without_losing_lives(self):
        lesson = self.start_lesson(self.ready_attempt())
        by_id = {e["id"]: e for e in lesson.exercises}
        while lesson.status == UseCaseLesson.IN_PROGRESS:
            self.post(f"/modelado/api/leccion/{lesson.id}/responder/",
                      {"exercise_id": lesson.queue[0], "answer": by_id[lesson.queue[0]]["answer"]})
            lesson.refresh_from_db()
        self.assertTrue(self.user.badges.filter(code="guided").exists())
        r = self.client.get("/")
        total = ReferenceUseCase.objects.filter(version__is_active=True).count()
        self.assertContains(r, f"Lecciones guiadas completadas: <strong>1 de {total}</strong>", html=False)

    def test_locked_badges_explain_how_to_earn_them(self):
        r = self.client.get("/")
        self.assertContains(r, BADGES["auditor"][2])
        self.assertNotContains(r, "Bloqueada")

    def test_cu09_filter_marks_every_resume_item_with_its_module(self):
        attempt = self.ready_attempt()
        self.new_attempt()
        self.start_lesson(attempt)
        self.client.post(f"/inspeccion/iniciar/{InspectionExercise.objects.first().id}/")
        r = self.client.get("/")
        for value, label in (("", "Todas"), ("elicitacion", "Elicitación"), ("modelado", "Modelado"),
                             ("inspeccion", "Inspección")):
            self.assertContains(r, f'data-filter="{value}"')
            self.assertContains(r, f">{label}</button>", html=False)
        html = r.content.decode()
        items = html.split('id="resume-list"', 1)[1].split("</ul>\n    </div>", 1)[0]
        top_level = [line for line in items.splitlines() if line.startswith("        <li")]
        self.assertTrue(top_level)
        self.assertTrue(all("data-module=" in line for line in top_level), top_level)
        for module in ("elicitacion", "modelado", "inspeccion"):
            self.assertIn(f'data-module="{module}"', items)

    def test_cu09_new_student_sees_empty_state_without_filter(self):
        r = self.client.get("/")
        self.assertContains(r, "Aún no tienes prácticas")
        self.assertNotContains(r, "data-filter-for")


class LevelTests(BaseCase):
    """CU-11: cinco niveles calibrados para los escenarios cargados (ACT-308)."""

    def max_points(self):
        """Puntos de un recorrido completo sin errores, pistas ni repeticiones."""
        total = 0
        for version in ScenarioVersion.objects.filter(is_active=True):
            rounds = version.questions.values("round_number").distinct().count()
            total += rounds * InterviewQuestion.POINTS[InterviewQuestion.HIGH]
            total += version.requirements.count() * classification_services.POINTS_PER_CORRECT
        for exercise in InspectionExercise.objects.filter(is_active=True):
            total += exercise.defect_count * inspection_services.POINTS_PER_DEFECT
        lesson_points = lessons.XP_BASE + lessons.XP_PER_LIFE * lessons.LIVES + USE_CASE_POINTS
        return total + ReferenceUseCase.objects.filter(version__is_active=True).count() * lesson_points

    def test_five_increasing_levels_and_last_one_reachable(self):
        thresholds = [t for t, _ in LEVELS]
        self.assertEqual(len(LEVELS), 5)
        self.assertEqual(thresholds, sorted(set(thresholds)))
        self.assertEqual(thresholds[0], 0)
        top = self.max_points()
        self.assertLessEqual(thresholds[-1], 0.85 * top, f"máximo posible: {top}")
        self.assertGreaterEqual(thresholds[-1], 0.6 * top, f"máximo posible: {top}")

    def test_level_for_boundaries(self):
        self.assertEqual(level_for(0)["number"], 1)
        self.assertEqual(level_for(LEVELS[1][0] - 1)["number"], 1)
        self.assertEqual(level_for(LEVELS[1][0])["number"], 2)
        last = level_for(LEVELS[-1][0])
        self.assertEqual((last["number"], last["next_at"], last["percent"]), (5, None, 100))
