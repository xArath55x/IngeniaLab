"""Lecciones guiadas de casos de uso (CU-02, estilo Duolingo)."""
import json
import tempfile
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from apps.classification.services import available_requirements
from apps.modeling import lessons
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.progress.services import total_points
from apps.progress.tests import BaseCase


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class LessonTests(BaseCase):
    def classify(self, attempt, overrides=None):
        """Clasifica todo lo descubierto con su tipo correcto, salvo las claves de overrides."""
        for req in available_requirements(attempt):
            category = (overrides or {}).get(req.key, req.expected_type)
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": category})

    def ready_attempt(self):
        attempt = self.finished_attempt()
        self.classify(attempt)
        return attempt

    def reference(self, key="UC-B1"):
        return ReferenceUseCase.objects.get(version=self.version, key=key)

    def start(self, attempt, ref):
        return self.client.post(f"/modelado/lecciones/{ref.id}/iniciar/", {"attempt": str(attempt.id)})

    def reply(self, lesson, exercise_id, value):
        return self.post(f"/modelado/api/leccion/{lesson.id}/responder/", {"exercise_id": exercise_id, "answer": value})

    def solve(self, lesson):
        lesson.refresh_from_db()
        by_id = {e["id"]: e for e in lesson.exercises}
        r = None
        while lesson.status == UseCaseLesson.IN_PROGRESS:
            r = self.reply(lesson, lesson.queue[0], by_id[lesson.queue[0]]["answer"]).json()
            lesson.refresh_from_db()
        return r

    def test_seed_loads_reference_use_cases(self):
        self.assertEqual(ReferenceUseCase.objects.filter(version=self.version).count(), 4)
        self.assertEqual(ReferenceUseCase.objects.filter(version__scenario_code="ESC-CAFETERIA-01").count(), 4)

    def test_locked_until_requirements_are_classified_as_rf(self):
        attempt = self.finished_attempt()
        status = lessons.lesson_status(attempt, self.reference())
        self.assertFalse(status["unlocked"])
        self.assertEqual(len(status["not_classified"]), 2)
        self.classify(attempt)
        self.assertTrue(lessons.lesson_status(attempt, self.reference())["unlocked"])

    def test_misclassified_requirement_keeps_lesson_locked(self):
        attempt = self.finished_attempt()
        self.classify(attempt, {"B04": "RNF"})
        status = lessons.lesson_status(attempt, self.reference())
        self.assertFalse(status["unlocked"])
        self.assertEqual(status["not_classified"], [self.version.requirements.get(key="B04").statement_text])

    def test_undiscovered_requirement_shows_topic_not_statement(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, rounds=1)
        self.post(f"/elicitacion/api/intento/{attempt.id}/finalizar/", {"confirm": True})
        self.classify(attempt)
        status = lessons.lesson_status(attempt, self.reference())
        self.assertEqual(status["not_discovered"], ["Préstamos"])
        page = self.client.get(f"/modelado/lecciones/?attempt={attempt.id}")
        self.assertContains(page, "Préstamos")
        self.assertNotContains(page, self.version.requirements.get(key="B04").statement_text)

    def test_cannot_start_locked_lesson(self):
        attempt = self.finished_attempt()
        r = self.start(attempt, self.reference())
        self.assertRedirects(r, f"/modelado/lecciones/?attempt={attempt.id}", fetch_redirect_response=False)
        self.assertFalse(UseCaseLesson.objects.exists())

    def test_lesson_page_never_sends_answers(self):
        attempt = self.ready_attempt()
        lesson_url = self.start(attempt, self.reference())["Location"]
        page = self.client.get(lesson_url)
        state = json.loads(page.content.decode().split('id="lesson-state" type="application/json">')[1].split("</script>")[0])
        self.assertNotIn("answer", state["current"])
        self.assertNotIn("explanation", state["current"])
        self.assertEqual(state["lives"], lessons.LIVES)

    def test_complete_lesson_awards_best_xp_once(self):
        attempt = self.ready_attempt()
        before = total_points(self.user)
        self.start(attempt, self.reference())
        r = self.solve(UseCaseLesson.objects.get())
        self.assertEqual(r["lesson_status"], "completed")
        self.assertEqual(r["xp"], lessons.XP_BASE + lessons.XP_PER_LIFE * lessons.LIVES)
        self.assertEqual(total_points(self.user), before + r["xp"])
        self.start(attempt, self.reference())
        self.solve(UseCaseLesson.objects.filter(status=UseCaseLesson.IN_PROGRESS).get())
        self.assertEqual(total_points(self.user), before + r["xp"])

    def test_wrong_answer_costs_a_life_and_repeats_at_the_end(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        first = lesson.queue[0]
        r = self.reply(lesson, first, -1).json()
        self.assertFalse(r["correct"])
        self.assertTrue(r["solution"] and r["explanation"])
        self.assertEqual(r["lives"], lessons.LIVES - 1)
        lesson.refresh_from_db()
        self.assertEqual(lesson.queue[-1], first)
        self.assertNotEqual(r["current"]["id"], first)

    def test_three_mistakes_fail_the_lesson(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        for _ in range(lessons.LIVES):
            lesson.refresh_from_db()
            r = self.reply(lesson, lesson.queue[0], -1).json()
        self.assertEqual(r["lesson_status"], "failed")
        self.assertIsNone(r["current"])
        lesson.refresh_from_db()
        self.assertEqual(self.reply(lesson, lesson.queue[0], 0).status_code, 400)
        # Reintentar crea una lección nueva con todas las vidas.
        self.start(attempt, self.reference())
        self.assertEqual(UseCaseLesson.objects.filter(status=UseCaseLesson.IN_PROGRESS).get().lives, lessons.LIVES)

    def test_must_answer_current_exercise(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        self.assertEqual(self.reply(lesson, lesson.queue[1], 0).status_code, 400)

    def test_start_resumes_lesson_in_progress(self):
        attempt = self.ready_attempt()
        first = self.start(attempt, self.reference())["Location"]
        self.assertEqual(self.start(attempt, self.reference())["Location"], first)
        self.assertEqual(UseCaseLesson.objects.count(), 1)

    def test_lessons_are_private(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        self.client.logout()
        self.assertEqual(self.reply(lesson, lesson.queue[0], 0).status_code, 401)
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.client.get(f"/modelado/leccion/{lesson.id}/").status_code, 404)
        self.assertEqual(self.reply(lesson, lesson.queue[0], 0).status_code, 404)

    def test_editor_is_prefilled_only_from_completed_lesson(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        r = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}")
        self.assertIsNone(r.context["form_data"])
        self.solve(lesson)
        r = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}")
        self.assertEqual(r.context["form_data"]["name"], "Registrar préstamo")
        self.assertEqual(r.context["form_data"]["attempt_id"], str(attempt.id))
        self.assertContains(r, "Prellenado con tu lección")

    def test_use_case_card_shows_only_solved_parts(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        state = lessons.state(lesson)
        self.assertTrue(all(part["values"] is None for part in state["built"]))
        first = lesson.queue[0]
        r = self.reply(lesson, first, next(e for e in lesson.exercises if e["id"] == first)["answer"]).json()
        solved = {p["id"]: p["values"] for p in r["built"]}
        self.assertIsNotNone(solved[first])
        self.assertTrue(all(v is None for k, v in solved.items() if k != first))

    def test_save_use_case_requires_completed_lesson_and_happens_once(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        url = f"/modelado/api/leccion/{lesson.id}/guardar/"
        self.assertEqual(self.post(url).status_code, 400)
        self.solve(lesson)
        before = total_points(self.user)
        r = self.post(url).json()
        self.assertTrue(r["ok"])
        self.assertIn("<svg", r["svg"])
        uc = self.user.use_cases.get()
        self.assertEqual((uc.name, uc.attempt_id), ("Registrar préstamo", attempt.id))
        self.assertTrue(hasattr(uc, "diagram"))
        again = self.post(url).json()
        self.assertTrue(again["saved_before"])
        self.assertEqual(again["id"], r["id"])
        self.assertEqual(self.user.use_cases.count(), 1)
        self.assertGreater(total_points(self.user), before)
        self.assertTrue(lessons.state(UseCaseLesson.objects.get())["saved"])

    def test_save_is_private(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        self.solve(lesson)
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").status_code, 404)

    def test_classification_links_to_lessons(self):
        attempt = self.ready_attempt()
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        self.assertContains(r, f"/modelado/lecciones/?attempt={attempt.id}")


class ExerciseTests(SimpleTestCase):
    def test_is_correct_for_each_type(self):
        cases = [
            ({"type": "choice", "answer": 2}, 2, True), ({"type": "choice", "answer": 2}, "x", False),
            ({"type": "multi", "answer": [0, 3]}, [3, 0], True), ({"type": "multi", "answer": [0, 3]}, [0], False),
            ({"type": "order", "answer": [0, 1, 2]}, [0, 1, 2], True), ({"type": "order", "answer": [0, 1, 2]}, [1, 0, 2], False),
            ({"type": "classify", "answer": {"0": "include"}}, {"0": "include"}, True),
            ({"type": "classify", "answer": {"0": "include"}}, {"0": "extend"}, False),
            ({"type": "classify", "answer": {"0": "include"}}, None, False),
        ]
        for exercise, value, expected in cases:
            with self.subTest(exercise=exercise, value=value):
                self.assertEqual(lessons.is_correct(exercise, value), expected)


class SeedValidationTests(BaseCase):
    def test_seed_rejects_use_case_built_on_non_functional_requirement(self):
        with open(settings.BASE_DIR / "data" / "usecases.json", encoding="utf-8") as fh:
            data = json.load(fh)
        data["use_cases"][0]["requirements"] = ["B07"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False)
            tmp.flush()
            with self.assertRaisesMessage(ValueError, "B07 debe ser un requisito funcional"):
                call_command("seed_ingenialab", usecases=tmp.name, stdout=StringIO())
