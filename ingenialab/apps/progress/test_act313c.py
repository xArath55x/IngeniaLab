"""Defectos de ACT-313A, ACT-313D y ACT-314B corregidos en ACT-313C.

- BR-11 (CP-14): una inspección sin hallazgos no se concluye ni da la insignia «Sin ayuda».
- DEF-S01: la API de la lección rechaza una respuesta vacía o incompleta sin quitar una vida.
- BR-09 (observación de la revisión del PR #43): al clasificar todos los enunciados, la clasificación
  terminó y su autoguardado se cierra.
"""
from apps.classification.services import available_requirements
from apps.inspection.models import InspectionExercise
from apps.modeling.models import UseCaseLesson
from apps.modeling.test_lessons import LessonHelpers, exercise
from apps.progress.models import PracticeCheckpoint
from apps.progress.services import evaluate_badges

from .tests import ALL_MODULES, BaseCase

SAVE = "/api/checkpoints/"
EMPTY_INSPECTION = "Registra al menos un hallazgo antes de concluir la práctica."


@ALL_MODULES
class EmptyInspectionTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.exercise = InspectionExercise.objects.get(code="INS-CONTROL-ESCOLAR-01")
        self.client.post(f"/inspeccion/iniciar/{self.exercise.id}/")
        self.attempt = self.user.inspections.latest("started_at")
        self.base = f"/inspeccion/api/intento/{self.attempt.id}/"

    def test_inspection_without_findings_cannot_be_concluded(self):
        r = self.post(self.base + "concluir/")
        self.assertEqual((r.status_code, r.json()["message"]), (400, EMPTY_INSPECTION))
        self.attempt.refresh_from_db()
        self.assertFalse(self.attempt.is_concluded)
        self.assertNotIn("no_hints", evaluate_badges(self.user) or [])
        self.assertFalse(self.user.badges.filter(code="no_hints").exists())

    def test_one_finding_is_enough_even_if_wrong(self):
        clean = self.exercise.fragments.filter(defect_type="").first()
        self.post(self.base + "hallazgo/", {"fragment_id": str(clean.id), "defect_type": "ambiguity"})
        r = self.post(self.base + "concluir/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["summary"]["precision"], 0.0)

    def test_page_requires_review_before_offering_to_finish(self):
        page = self.client.get(f"/inspeccion/intento/{self.attempt.id}/")
        self.assertContains(page, "¿Qué cambiarías en este fragmento?")
        self.assertNotContains(page, "Ver resultado")


class EmptyLessonAnswerTests(LessonHelpers, BaseCase):
    def setUp(self):
        super().setUp()
        attempt = self.ready_attempt()
        self.start(attempt, self.reference())
        self.lesson = UseCaseLesson.objects.get()

    def current(self):
        self.lesson.refresh_from_db()
        return exercise(self.lesson, self.lesson.queue[0])

    def assert_rejected_without_cost(self, value):
        ex = self.current()
        before = (self.lesson.lives, self.lesson.mistakes, list(self.lesson.queue))
        r = self.reply(self.lesson, ex["id"], value)
        self.assertEqual((r.status_code, r.json()["message"]), (400, "Elige tu respuesta antes de comprobar."))
        self.lesson.refresh_from_db()
        self.assertEqual((self.lesson.lives, self.lesson.mistakes, self.lesson.queue), before)

    def test_empty_values_do_not_cost_a_life(self):
        for value in (None, "", [], {}, True, "x"):
            with self.subTest(value=value):
                self.assert_rejected_without_cost(value)

    def test_incomplete_answers_by_type_do_not_cost_a_life(self):
        seen = set()
        for _ in range(len(self.lesson.exercises)):
            ex = self.current()
            if ex["type"] not in seen:
                seen.add(ex["type"])
                ids = [o["id"] for o in ex["options"]]
                incomplete = {  # Lo que la pantalla no deja enviar: id inexistente o respuesta a medias.
                    "choice": lambda: max(ids) + 1,
                    "multi": lambda: ex["answer"][:-1] or [max(ids) + 1],
                    "order": lambda: ex["answer"][:-1],
                    "classify": lambda: {str(ids[0]): ex["answer"][str(ids[0])]},
                }[ex["type"]]()
                if ex["type"] != "classify" or len(ids) > 1:
                    with self.subTest(type=ex["type"]):
                        self.assert_rejected_without_cost(incomplete)
            self.reply(self.lesson, ex["id"], ex["answer"])  # avanza al siguiente ejercicio
            self.lesson.refresh_from_db()
            if self.lesson.status != UseCaseLesson.IN_PROGRESS:
                break
        self.assertGreaterEqual(seen, {"choice", "multi", "order"})


@ALL_MODULES
class ClassificationCheckpointTests(BaseCase):
    def save(self, attempt):
        return self.post(SAVE, {"module": "classification", "key": str(attempt.id), "revision": 0,
                                "payload": {"selected": None}})

    def classify_all(self, attempt, until=None):
        reqs = list(available_requirements(attempt))
        for req in reqs[:until]:
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": req.expected_type})
        return reqs

    def test_classifying_everything_closes_the_checkpoint(self):
        attempt = self.finished_attempt()
        reqs = self.classify_all(attempt, until=-1)
        self.assertEqual(self.save(attempt).status_code, 200)
        self.assertTrue(PracticeCheckpoint.objects.filter(module="classification").exists())
        self.classify_all(attempt)
        self.assertFalse(PracticeCheckpoint.objects.filter(module="classification").exists())
        r = self.save(attempt)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "practice_closed"))
        self.assertGreater(len(reqs), 1)

    def test_dashboard_does_not_offer_to_resume_finished_classification(self):
        attempt = self.finished_attempt()
        self.classify_all(attempt, until=-1)
        self.save(attempt)
        self.classify_all(attempt)
        self.assertNotContains(self.client.get("/"), f"/api/checkpoints/classification/{attempt.id}/")
