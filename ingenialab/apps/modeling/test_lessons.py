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
def wrong_answer(exercise):
    """Respuesta completa (como la que habilita «Comprobar») pero incorrecta, para cualquier tipo de ejercicio."""
    ids = [o["id"] for o in exercise["options"]]
    kind, answer = exercise["type"], exercise["answer"]
    if kind == "choice":
        return next(i for i in ids if i != answer)
    if kind == "multi":
        return [i for i in ids if i not in answer][:1] + answer[1:]
    if kind == "order":
        return list(reversed(answer))
    categories = [c["id"] for c in exercise["categories"]]
    return {str(i): next(c for c in categories if c != answer[str(i)]) for i in ids}


def exercise(lesson, exercise_id):
    return next(e for e in lesson.exercises if e["id"] == exercise_id)


class LessonHelpers:
    """Pasos comunes para llegar a una lección; los reutilizan otras pruebas (p. ej. progress/test_act313c)."""

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


class LessonTests(LessonHelpers, BaseCase):

    def test_seed_loads_reference_use_cases(self):
        self.assertEqual(ReferenceUseCase.objects.filter(version=self.version).count(), 4)
        self.assertEqual(ReferenceUseCase.objects.filter(version__scenario_code="ESC-CAFETERIA-01").count(), 4)
        # Escenario de tutorías (ACT-329A): 11 requisitos y 2 casos de uso guiados.
        tutorias = ReferenceUseCase.objects.filter(version__scenario_code="ESC-TUTORIAS-01")
        self.assertEqual(sorted(tutorias.values_list("key", flat=True)), ["UC-T1", "UC-T2"])
        self.assertEqual(tutorias.first().version.requirements.count(), 11)
        # Escenarios del consultorio y del gimnasio (ACT-329B): 11 requisitos y 2 casos de uso guiados cada uno.
        for code, keys in (("ESC-CONSULTORIO-01", ["UC-M1", "UC-M2"]), ("ESC-GIMNASIO-01", ["UC-G1", "UC-G2"])):
            refs = ReferenceUseCase.objects.filter(version__scenario_code=code)
            self.assertEqual(sorted(refs.values_list("key", flat=True)), keys)
            self.assertEqual(refs.first().version.requirements.count(), 11)

    def test_locked_until_requirements_are_classified_as_rf(self):
        attempt = self.finished_attempt()
        status = lessons.lesson_status(attempt, self.reference())
        self.assertFalse(status["unlocked"])
        self.assertEqual(len(status["not_classified"]), 2)
        self.classify(attempt)
        self.assertTrue(lessons.lesson_status(attempt, self.reference())["unlocked"])

    def test_return_lesson_needs_return_goal_and_fine_rule(self):
        """ACT-328: «Registrar devolución» tiene su propia meta (B12) y B05 es su regla de multa."""
        ref = self.reference("UC-B2")
        self.assertEqual(ref.requirement_keys, ["B12", "B05"])
        locked = self.finished_attempt()
        self.classify(locked, overrides={"B12": "RNF"})
        self.assertFalse(lessons.lesson_status(locked, ref)["unlocked"])
        self.assertTrue(lessons.lesson_status(self.ready_attempt(), ref)["unlocked"])

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
        self.assertNotIn("order", state["current"])
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
        r = self.reply(lesson, first, wrong_answer(exercise(lesson, first))).json()
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
            r = self.reply(lesson, lesson.queue[0], wrong_answer(exercise(lesson, lesson.queue[0]))).json()
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

    def test_editor_opens_saved_use_case_of_lesson(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        self.solve(lesson)
        saved = self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").json()
        r = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}")
        self.assertRedirects(r, saved["edit_url"])
        self.assertEqual(self.user.use_cases.count(), 1)

    def editor_save(self, lesson, **extra):
        spec = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}").context["form_data"]
        return self.post("/modelado/api/guardar/", {**spec, **extra}).json()

    def solved_lesson(self):
        self.start(self.ready_attempt(), self.reference())
        lesson = UseCaseLesson.objects.get()
        self.solve(lesson)
        return lesson

    def test_editor_save_is_linked_to_lesson_without_duplicates(self):
        lesson = self.solved_lesson()
        self.assertContains(self.client.get(f"/modelado/nuevo/?leccion={lesson.id}"), f'data-lesson-id="{lesson.id}"')
        saved = self.editor_save(lesson, lesson_id=str(lesson.id))
        self.assertTrue(saved["ok"])
        lesson.refresh_from_db()
        self.assertEqual(str(lesson.use_case_id), saved["id"])
        again = self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").json()
        self.assertTrue(again["saved_before"])
        self.assertEqual(again["id"], saved["id"])
        self.assertEqual(self.user.use_cases.count(), 1)

    def test_stale_editor_updates_use_case_already_saved_by_lesson(self):
        lesson = self.solved_lesson()
        spec = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}").context["form_data"]
        saved = self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").json()
        again = self.post("/modelado/api/guardar/", {**spec, "lesson_id": str(lesson.id), "name": "Registrar préstamo editado"}).json()
        self.assertEqual(again["id"], saved["id"])
        self.assertEqual(self.user.use_cases.get().name, "Registrar préstamo editado")

    def test_foreign_or_invalid_lesson_is_not_linked(self):
        lesson = self.solved_lesson()
        spec = self.client.get(f"/modelado/nuevo/?leccion={lesson.id}").context["form_data"]
        self.assertTrue(self.post("/modelado/api/guardar/", {**spec, "lesson_id": "no-es-uuid"}).json()["ok"])
        self.client.login(username="otro", password="ClaveSegura123")
        other = self.post("/modelado/api/guardar/", {**spec, "attempt_id": None, "lesson_id": str(lesson.id)})
        lesson.refresh_from_db()
        self.assertIsNone(lesson.use_case_id)
        self.assertNotEqual(other.status_code, 500)

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

    def test_classification_links_to_use_case_wizard(self):
        attempt = self.ready_attempt()
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        self.assertContains(r, f"/modelado/asistente/?attempt={attempt.id}")

    def test_multiple_correct_answers_are_graded_as_a_set(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        pre = next(e for e in lesson.exercises if e["id"] == "preconditions")
        self.assertEqual(pre["type"], "multi")
        self.assertEqual(len(pre["answer"]), 2)
        self.assertEqual(len(pre["options"]), 4)
        self.assertFalse(lessons.is_correct(pre, pre["answer"][:1]))
        self.assertTrue(lessons.is_correct(pre, list(reversed(pre["answer"]))))
        ids = [e["id"] for e in lesson.exercises]
        self.assertLess(ids.index("main_flow_select"), ids.index("main_flow"))
        # El navegador sabe cuántas marcar, pero no cuáles.
        shown = lessons.public(pre)
        self.assertEqual(shown["required"], 2)
        self.assertNotIn("answer", shown)

    def test_answer_reveals_correct_options_after_grading(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        first = next(e for e in lesson.exercises if e["id"] == lesson.queue[0])
        r = self.reply(lesson, first["id"], wrong_answer(first)).json()
        self.assertEqual(r["correct_ids"], [first["answer"]])


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


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class TutoriasScenarioTests(BaseCase):
    """Escenario de tutorías (ACT-329A): entrevista, clasificación y sus dos lecciones guiadas."""

    SCENARIO = "ESC-TUTORIAS-01"
    LESSONS = (("UC-T1", "Agendar tutoría"), ("UC-T2", "Registrar seguimiento de tutoría"))

    classify, ready_attempt, reference = LessonTests.classify, LessonTests.ready_attempt, LessonTests.reference
    start, reply, solve = LessonTests.start, LessonTests.reply, LessonTests.solve

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.version = cls.version.__class__.objects.get(scenario_code=cls.SCENARIO)

    def test_interview_unlocks_and_completes_both_lessons(self):
        attempt = self.ready_attempt()
        self.assertEqual(attempt.classifications.filter(is_correct=True).count(), 11)
        for key, name in self.LESSONS:
            with self.subTest(key=key):
                ref = self.reference(key)
                self.assertTrue(lessons.lesson_status(attempt, ref)["unlocked"])
                self.start(attempt, ref)
                lesson = UseCaseLesson.objects.get(reference=ref)
                self.assertEqual(self.solve(lesson)["lesson_status"], "completed")
                r = self.post(f"/modelado/api/leccion/{lesson.id}/guardar/").json()
                self.assertIn("<svg", r["svg"])
                self.assertTrue(self.user.use_cases.filter(name=name).exists())


class ConsultorioScenarioTests(TutoriasScenarioTests):
    """Escenario del consultorio médico (ACT-329B): entrevista, clasificación y sus dos lecciones guiadas."""

    SCENARIO = "ESC-CONSULTORIO-01"
    LESSONS = (("UC-M1", "Solicitar cita médica"), ("UC-M2", "Registrar consulta médica"))


class GimnasioScenarioTests(TutoriasScenarioTests):
    """Escenario del gimnasio (ACT-329B): entrevista, clasificación y sus dos lecciones guiadas."""

    SCENARIO = "ESC-GIMNASIO-01"
    LESSONS = (("UC-G1", "Reservar clase grupal"), ("UC-G2", "Pasar lista de clase"))


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


class QuestionClarityTests(BaseCase):
    """Preguntas de las lecciones: sin ambigüedad y con el caso de uso en cada enunciado."""

    def exercises(self, ref):
        statements = list(ref.version.requirements.filter(key__in=ref.requirement_keys)
                          .values_list("statement_text", flat=True))
        return {e["id"]: e for e in lessons.build_exercises(ref, statements, seed="claridad")}

    def test_every_prompt_names_the_use_case(self):
        for ref in ReferenceUseCase.objects.all():
            for ex_id, exercise in self.exercises(ref).items():
                with self.subTest(caso=ref.key, ejercicio=ex_id):
                    if ex_id != "name":  # La de nombre pregunta justamente cuál es.
                        self.assertIn(f"«{ref.spec['name']}»", exercise["prompt"])

    def test_flow_selection_asks_for_one_first_step(self):
        for ref in ReferenceUseCase.objects.all():
            exercise = self.exercises(ref)["main_flow_select"]
            with self.subTest(caso=ref.key):
                self.assertEqual(exercise["type"], "choice")
                self.assertIn("primer paso", exercise["prompt"])
                options = [o["text"] for o in exercise["options"]]
                self.assertEqual(options[exercise["answer"]], ref.spec["main_flow"][0])
                self.assertEqual(len(options), 3)

    def test_card_waits_until_the_full_flow_is_ordered(self):
        ref = ReferenceUseCase.objects.get(version=self.version, key="UC-B1")
        lesson = UseCaseLesson(exercises=list(self.exercises(ref).values()), solved=["main_flow_select"])
        self.assertNotIn("main_flow_select", [part["id"] for part in lessons.built(lesson)])

    def test_every_reference_use_case_passes_the_editor_validation(self):
        from apps.interviews.models import StudentAttempt
        from apps.modeling.forms import UseCaseForm

        for ref in ReferenceUseCase.objects.select_related("version"):
            attempt = StudentAttempt.objects.create(user=self.user, version=ref.version,
                                                    status=StudentAttempt.CLASSIFYING)
            form = UseCaseForm(data={**ref.spec, "attempt_id": str(attempt.id)}, user=self.user)
            with self.subTest(caso=ref.key):
                self.assertTrue(form.is_valid(), form.errors)


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class RefreshInProgressTests(BaseCase):
    """Al corregir el contenido, las lecciones a medias lo toman sin perder lo resuelto (seed_ingenialab)."""

    classify, ready_attempt, reference = LessonTests.classify, LessonTests.ready_attempt, LessonTests.reference
    start, reply, solve = LessonTests.start, LessonTests.reply, LessonTests.solve

    def test_seed_updates_in_progress_lesson_text_and_keeps_progress(self):
        attempt = self.ready_attempt()
        ref = self.reference()
        self.start(attempt, ref)
        lesson = UseCaseLesson.objects.get()
        first = lesson.queue[0]
        self.reply(lesson, first, {e["id"]: e for e in lesson.exercises}[first]["answer"])
        lesson.refresh_from_db()
        # Simula una lección creada con el texto anterior.
        old = [{**e, "prompt": "Texto anterior"} for e in lesson.exercises]
        UseCaseLesson.objects.filter(pk=lesson.pk).update(exercises=old)
        call_command("seed_ingenialab", stdout=StringIO())
        refreshed = UseCaseLesson.objects.get()
        self.assertNotIn("Texto anterior", [e["prompt"] for e in refreshed.exercises])
        self.assertEqual(refreshed.solved, lesson.solved)
        self.assertEqual(refreshed.queue, lesson.queue)
        self.assertEqual(refreshed.lives, lesson.lives)
        self.assertEqual(refreshed.status, UseCaseLesson.IN_PROGRESS)

    def test_finished_lessons_are_not_touched(self):
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        lesson = UseCaseLesson.objects.get()
        self.solve(lesson)
        UseCaseLesson.objects.filter(pk=lesson.pk).update(exercises=[{"id": "name", "prompt": "Texto anterior"}])
        call_command("seed_ingenialab", stdout=StringIO())
        self.assertEqual(UseCaseLesson.objects.get().exercises, [{"id": "name", "prompt": "Texto anterior"}])


class FlowOrderTests(BaseCase):
    """El orden del flujo debe deducirse del texto: lo respalda la pista del enunciado."""

    def test_every_main_flow_starts_with_the_actor(self):
        for ref in ReferenceUseCase.objects.all():
            with self.subTest(caso=ref.key):
                self.assertFalse(ref.spec["main_flow"][0].startswith("El sistema"), ref.spec["main_flow"][0])


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class OrderFeedbackTests(BaseCase):
    """Al fallar el orden, la respuesta trae el orden correcto para marcar cada paso en verde o rojo."""

    classify = LessonTests.classify

    def test_order_answer_returns_correct_order(self):
        attempt = LessonTests.ready_attempt(self)
        LessonTests.start(self, attempt, LessonTests.reference(self))
        lesson = UseCaseLesson.objects.get()
        while lesson.queue[0] != "main_flow":
            first = lesson.queue[0]
            LessonTests.reply(self, lesson, first, {e["id"]: e for e in lesson.exercises}[first]["answer"])
            lesson.refresh_from_db()
        expected = next(e for e in lesson.exercises if e["id"] == "main_flow")["answer"]
        wrong = [expected[1], expected[0], *expected[2:]]
        r = LessonTests.reply(self, lesson, "main_flow", wrong).json()
        self.assertFalse(r["correct"])
        self.assertEqual(r["correct_order"], expected)
        self.assertEqual(r["correct_ids"], [])

    def test_other_exercises_do_not_send_an_order(self):
        attempt = LessonTests.ready_attempt(self)
        LessonTests.start(self, attempt, LessonTests.reference(self))
        lesson = UseCaseLesson.objects.get()
        r = LessonTests.reply(self, lesson, lesson.queue[0], wrong_answer(exercise(lesson, lesson.queue[0]))).json()
        self.assertEqual(r["correct_order"], [])
