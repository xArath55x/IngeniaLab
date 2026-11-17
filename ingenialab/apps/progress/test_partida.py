"""Partida única: Entrevista → Clasificación → Modelado → Inspección, con checkpoint por etapa."""
from unittest import mock

from django.conf import settings
from django.test import override_settings

from apps.classification.services import available_requirements
from apps.inspection.models import InspectionAttempt
from apps.interviews.models import ScenarioVersion, StudentAttempt
from apps.modeling import lessons as lesson_engine
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.progress import partidas
from apps.progress.models import Partida

from .tests import BaseCase


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class PartidaTests(BaseCase):
    def start(self):
        # Escenario fijo (Biblioteca) para que las ayudas de BaseCase respondan sus preguntas.
        with mock.patch.object(partidas.random, "choice", lambda options: self.version
                               if self.version in options else options[0]):
            r = self.client.post("/partida/nueva/")
        return r, Partida.objects.get(user=self.user, finished_at__isnull=True, abandoned_at__isnull=True)

    def classify_all(self, attempt):
        for req in available_requirements(attempt):
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": req.expected_type})

    def complete_lessons(self, attempt):
        for ref in ReferenceUseCase.objects.filter(version=attempt.version):
            if not lesson_engine.lesson_status(attempt, ref)["unlocked"]:
                continue
            self.client.post(f"/modelado/lecciones/{ref.id}/iniciar/", {"attempt": str(attempt.id)})
            lesson = UseCaseLesson.objects.get(user=self.user, reference=ref, status=UseCaseLesson.IN_PROGRESS)
            by_id = {e["id"]: e for e in lesson.exercises}
            while lesson.status == UseCaseLesson.IN_PROGRESS:
                self.post(f"/modelado/api/leccion/{lesson.id}/responder/",
                          {"exercise_id": lesson.queue[0], "answer": by_id[lesson.queue[0]]["answer"]})
                lesson.refresh_from_db()

    def test_new_student_sees_start_button(self):
        r = self.client.get("/")
        self.assertContains(r, "Iniciar nueva partida")
        self.assertContains(r, 'action="/partida/nueva/"')
        self.assertNotContains(r, "Partida en curso")

    def test_start_creates_partida_and_opens_the_interview(self):
        r, partida = self.start()
        self.assertRedirects(r, f"/elicitacion/intento/{partida.attempt_id}/")
        self.assertEqual(partida.attempt.user, self.user)
        self.assertEqual((partida.stage, partida.percent), (Partida.INTERVIEW, 0))
        r = self.client.get("/")
        self.assertContains(r, "Partida en curso")
        self.assertContains(r, "Continuar partida")
        self.assertNotContains(r, "Iniciar nueva partida")

    def test_only_one_partida_in_progress(self):
        self.start()
        r = self.client.post("/partida/nueva/", follow=True)
        self.assertContains(r, "Ya tienes una partida en curso")
        self.assertEqual(Partida.objects.filter(user=self.user).count(), 1)

    def test_random_scenario_prefers_unplayed_ones(self):
        active = list(ScenarioVersion.objects.filter(is_active=True))
        played = active[:-1]
        for version in played:
            attempt = StudentAttempt.objects.create(user=self.user, version=version)
            Partida.objects.create(user=self.user, attempt=attempt, abandoned_at=attempt.started_at)
        for _ in range(5):
            self.assertEqual(partidas._pick_version(self.user), active[-1])

    def test_full_run_reaches_100_with_a_checkpoint_per_stage(self):
        _, partida = self.start()
        attempt = partida.attempt
        self.ask_rounds(attempt, rounds=3)
        state = partidas.state(partida)
        self.assertEqual(state["current"], Partida.INTERVIEW)
        self.assertTrue(0 < state["percent"] < 25)

        self.ask_rounds(attempt)  # Termina la entrevista.
        partida.refresh_from_db()
        self.assertRedirects(self.client.get("/partida/continuar/"), f"/clasificacion/intento/{attempt.id}/")
        partida.refresh_from_db()
        self.assertEqual((partida.stage, partida.percent), (Partida.CLASSIFICATION, 25))
        self.assertIn(Partida.INTERVIEW, partida.checkpoints)

        self.classify_all(attempt)
        r = self.client.get("/partida/continuar/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/modelado/lecciones/", r["Location"])
        partida.refresh_from_db()
        self.assertEqual(partida.stage, Partida.MODELING)
        self.assertIn(Partida.CLASSIFICATION, partida.checkpoints)

        self.complete_lessons(attempt)
        r = self.client.get("/partida/continuar/")
        partida.refresh_from_db()
        self.assertEqual(partida.stage, Partida.INSPECTION)
        self.assertIsNotNone(partida.inspection)
        self.assertRedirects(r, f"/inspeccion/intento/{partida.inspection_id}/")
        # Volver a continuar no crea otra inspección.
        self.client.get("/partida/continuar/")
        self.assertEqual(InspectionAttempt.objects.filter(user=self.user).count(), 1)

        base = f"/inspeccion/api/intento/{partida.inspection_id}/"
        for fragment in partida.inspection.exercise.fragments.exclude(defect_type=""):
            self.post(base + "hallazgo/", {"fragment_id": str(fragment.id), "defect_type": fragment.defect_type})
        self.post(base + "concluir/")
        r = self.client.get("/")
        partida.refresh_from_db()
        self.assertEqual((partida.stage, partida.percent), (Partida.DONE, 100))
        self.assertIsNotNone(partida.finished_at)
        self.assertEqual(set(partida.checkpoints), set(partidas.STAGE_ORDER))
        self.assertContains(r, "Partidas anteriores")
        self.assertContains(r, "Iniciar nueva partida")

    def test_stage_pages_show_the_partida_strip(self):
        _, partida = self.start()
        r = self.client.get(f"/elicitacion/intento/{partida.attempt_id}/")
        self.assertContains(r, "partida-strip")
        self.assertContains(r, "Etapa 1 de 4: Entrevista")
        self.assertNotContains(self.client.get("/"), "partida-strip")

    def test_abandon_keeps_the_work_and_allows_a_new_partida(self):
        _, partida = self.start()
        self.ask_rounds(partida.attempt, rounds=2)
        r = self.client.post("/partida/abandonar/", follow=True)
        self.assertContains(r, "Abandonaste la partida")
        partida.refresh_from_db()
        self.assertIsNotNone(partida.abandoned_at)
        self.assertTrue(StudentAttempt.objects.filter(id=partida.attempt_id).exists())
        self.assertContains(r, "Abandonada")
        self.start()
        self.assertEqual(Partida.objects.filter(user=self.user).count(), 2)

    def test_partida_routes_need_login_and_post(self):
        self.assertEqual(self.client.get("/partida/nueva/").status_code, 405)
        self.assertEqual(self.client.get("/partida/abandonar/").status_code, 405)
        self.assertRedirects(self.client.get("/partida/continuar/"), "/")
        self.client.logout()
        r = self.client.post("/partida/nueva/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cuentas/login/", r["Location"])

    def test_other_students_partida_is_invisible(self):
        _, partida = self.start()
        self.client.logout()
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertIsNone(partidas.active(self.other))
        self.assertNotContains(self.client.get("/"), partida.attempt.version.title + "</strong>")
