"""Partida única: Entrevista → Clasificación → Modelado → Inspección, con checkpoint por etapa."""
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from reportlab import rl_config

from apps.accounts.models import AccountRole
from apps.classification.services import available_requirements
from apps.inspection import guided
from apps.inspection.models import InspectionAttempt
from apps.interviews.models import ScenarioVersion, StudentAttempt
from apps.modeling import lessons as lesson_engine
from apps.modeling.models import ReferenceUseCase, UseCaseLesson
from apps.progress import partidas
from apps.progress.models import Partida, ReportSubmission

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

        fragments = partida.inspection.exercise.fragments.exclude(defect_type="")
        for index, fragment in enumerate(fragments):
            answer = fragment.defect_type
            if index == 0:
                answer = next(key for key, _ in guided.options(fragment) if key != fragment.defect_type)
            self.client.post(reverse("inspection:answer", args=[partida.inspection_id, fragment.id]),
                             {"defect_type": answer})
            if index == 0:
                stage = partidas.state(partida)["stages"][-1]
                self.assertGreater(stage["percent"], 0)
                self.assertIn("1 de", stage["detail"])
        self.assertEqual(partidas.state(partida)["percent"], 99)
        self.user.use_cases.create(name="Caso de esta partida", attempt=attempt, actors={}, main_flow=[])
        self.user.use_cases.create(name="Caso ajeno a esta partida", actors={}, main_flow=[])
        report_url = reverse("progress:partida_report", args=[partida.id])
        download_url = reverse("progress:partida_report_download", args=[partida.id])
        submission_url = reverse("progress:partida_report_submit", args=[partida.id])
        self.assertEqual(self.client.get(report_url).status_code, 404)
        finish = self.client.post(reverse("inspection:finish", args=[partida.inspection_id]))
        self.assertRedirects(finish, report_url)
        self.assertRedirects(self.client.get(reverse("inspection:inspect", args=[partida.inspection_id])), report_url)

        report = self.client.get(report_url)
        for section in ("Entrevista", "Clasificación", "Modelado", "Inspección"):
            self.assertContains(report, f"<h2>{section}</h2>", html=True)
        self.assertContains(report, "Caso de esta partida")
        self.assertContains(report, "Registrar préstamo")
        self.assertNotContains(report, "Caso ajeno a esta partida")
        with mock.patch.object(rl_config, "pageCompression", 0):
            pdf = self.client.get(download_url)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertIn(b"Caso de esta partida", pdf.content)
        self.assertNotIn(b"Caso ajeno a esta partida", pdf.content)
        self.assertIn(b"Lecci", pdf.content)

        r = self.client.get("/")
        partida.refresh_from_db()
        self.assertEqual((partida.stage, partida.percent), (Partida.DONE, 100))
        self.assertIsNotNone(partida.finished_at)
        self.assertEqual(set(partida.checkpoints), set(partidas.STAGE_ORDER))
        self.assertContains(r, "Partidas anteriores")
        self.assertContains(r, report_url)
        self.assertContains(r, "Iniciar nueva partida")

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(report_url).status_code, 404)
        self.assertEqual(self.client.get(download_url).status_code, 404)
        self.assertEqual(self.client.post(submission_url).status_code, 404)
        self.client.force_login(self.user)
        AccountRole.objects.create(user=self.other, role=AccountRole.Role.TEACHER)
        report = self.client.get(report_url)
        self.assertContains(report, submission_url)
        self.assertContains(report, f'<option value="{self.other.username}">@{self.other.username}</option>', html=True)
        with mock.patch.object(rl_config, "pageCompression", 0):
            sent = self.client.post(submission_url, {"teacher": self.other.username})
        submission = ReportSubmission.objects.get(teacher=self.other)
        self.assertRedirects(sent, reverse("progress:submission_detail", args=[submission.pk]))
        self.assertIn(b"Caso de esta partida", bytes(submission.pdf))
        self.assertNotIn(b"Caso ajeno a esta partida", bytes(submission.pdf))

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

    def test_short_interview_does_not_skip_modeling(self):
        _, partida = self.start()
        attempt = partida.attempt
        self.ask_rounds(attempt, rounds=1)
        self.post(f"/elicitacion/api/intento/{attempt.id}/finalizar/", {"confirm": True})
        partida.refresh_from_db()
        attempt = partida.attempt
        self.classify_all(attempt)
        state = partidas.state(partida)
        self.assertEqual(state["current"], Partida.MODELING)
        refs = ReferenceUseCase.objects.filter(version=attempt.version)
        self.assertIn(f"0 de {refs.count()} lecciones", [s["detail"] for s in state["stages"]])
        # Todas se pueden jugar en la partida; lo que faltó se avisa en vez de bloquear.
        page = self.client.get(f"/modelado/lecciones/?attempt={attempt.id}")
        self.assertNotContains(page, "Para desbloquearla")
        self.assertContains(page, "En tu entrevista no descubriste")
        for ref in refs:
            self.assertTrue(lesson_engine.lesson_status(attempt, ref)["unlocked"])
        # Fuera de una partida (abandonada) vuelve el desbloqueo por requisitos.
        partidas.abandon(partida)
        self.assertFalse(all(lesson_engine.lesson_status(attempt, ref)["unlocked"] for ref in refs))
