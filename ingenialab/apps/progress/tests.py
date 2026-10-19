"""Pruebas de integración de los casos de uso CU-01 a CU-05 (evidencia para VR-01)."""
import json
import tempfile
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.classification.models import StudentClassification
from apps.inspection.models import InspectionExercise
from apps.interviews.models import ScenarioVersion, StudentAttempt
from apps.modeling.models import UseCaseSpecification
from integrations.plantuml import service as plantuml


@override_settings(PLANTUML_ALLOW_FALLBACK=True, PLANTUML_JAR="/no/existe-prueba.jar")
class BaseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_ingenialab", stdout=StringIO())
        cls.user = User.objects.create_user("alumno", password="ClaveSegura123", first_name="Ana Alumna")
        cls.other = User.objects.create_user("otro", password="ClaveSegura123")
        cls.version = ScenarioVersion.objects.get(scenario_code="ESC-BIBLIOTECA-01")

    def setUp(self):
        self.client.login(username="alumno", password="ClaveSegura123")

    def post(self, url, data=None):
        return self.client.post(url, json.dumps(data or {}), content_type="application/json")

    def new_attempt(self):
        self.client.post(f"/elicitacion/iniciar/{self.version.id}/")
        return StudentAttempt.objects.filter(user=self.user).latest("started_at")

    def ask(self, attempt, question):
        return self.post(f"/elicitacion/api/intento/{attempt.id}/preguntar/", {"question_id": str(question.id)})

    def ask_rounds(self, attempt, quality="high", rounds=None):
        """Responde las rondas eligiendo siempre la opción de la calidad indicada."""
        numbers = sorted(set(self.version.questions.values_list("round_number", flat=True)))[:rounds]
        for n in numbers:
            self.ask(attempt, self.version.questions.get(round_number=n, quality=quality))

    def finished_attempt(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt)
        attempt.refresh_from_db()
        return attempt


ALL_MODULES = override_settings(INGENIALAB_MODULES=["interviews", "classification", "modeling", "inspection", "reports", "progress"])


class AuthTests(BaseCase):
    def test_rf09_login_failure_shows_error(self):
        self.client.logout()
        r = self.client.post("/cuentas/login/", {"username": "alumno", "password": "mala"})
        self.assertContains(r, "Usuario o contraseña incorrectos")

    def test_pages_require_login(self):
        self.client.logout()
        r = self.client.get("/elicitacion/")
        self.assertRedirects(r, "/cuentas/login/?next=/elicitacion/")

    def test_rf12_api_returns_401_when_session_expired(self):
        attempt = self.new_attempt()
        self.client.logout()
        r = self.post(f"/elicitacion/api/intento/{attempt.id}/preguntar/", {})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"], "session_expired")

    def test_data_isolation_between_students(self):
        attempt = self.new_attempt()
        self.client.logout()
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.client.get(f"/elicitacion/intento/{attempt.id}/").status_code, 404)

    def test_signup_creates_account_and_logs_in(self):
        self.client.logout()
        r = self.client.post("/cuentas/registro/", {
            "username": "nuevo", "first_name": "Nuevo", "email": "n@uaz.edu.mx",
            "password1": "Zacatecas#2026", "password2": "Zacatecas#2026"})
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="nuevo").exists())


class InterviewTests(BaseCase):
    def test_cu01_round_offers_three_options_one_per_quality(self):
        attempt = self.new_attempt()
        r = self.client.get(f"/elicitacion/intento/{attempt.id}/")
        options = r.context["options"]
        self.assertEqual(len(options), 3)
        self.assertNotIn("quality", options[0])  # la calidad no se revela al estudiante
        qualities = sorted(self.version.questions.get(id=o["id"]).quality for o in options)
        self.assertEqual(qualities, ["high", "low", "medium"])

    def test_cu01_nine_questions_finish_automatically_with_scoring(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, quality="medium", rounds=8)
        last = self.version.questions.get(round_number=9, quality="high")
        r = self.ask(attempt, last).json()
        self.assertTrue(r["finished"])
        self.assertEqual(r["progress"], {"asked": 9, "max": 9})
        self.assertEqual(r["summary"]["score"], 8 * 5 + 10)
        self.assertEqual(r["summary"]["counts"], {"high": 1, "medium": 8, "low": 0})
        self.assertIsNotNone(r["summary"]["review"][0]["best"])  # sugiere la mejor opción
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, StudentAttempt.CLASSIFYING)
        self.assertEqual(attempt.interview_score, 50)
        # Tras finalizar se bloquean nuevas preguntas.
        self.assertEqual(self.ask(attempt, last).status_code, 400)

    def test_low_quality_answers_score_zero(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, quality="low")
        attempt.refresh_from_db()
        self.assertEqual(attempt.interview_score, 0)

    def test_only_current_round_options_are_accepted(self):
        attempt = self.new_attempt()
        future = self.version.questions.get(round_number=3, quality="high")
        r = self.ask(attempt, future)
        self.assertEqual(r.status_code, 400)
        self.assertIn("tres preguntas", r.json()["message"])

    def test_cu01_e1_early_finish_asks_confirmation(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, rounds=2)
        r = self.post(f"/elicitacion/api/intento/{attempt.id}/finalizar/", {"confirm": False}).json()
        self.assertTrue(r["needs_confirmation"])
        self.assertEqual(r["pending"], 7)
        r = self.post(f"/elicitacion/api/intento/{attempt.id}/finalizar/", {"confirm": True}).json()
        self.assertEqual(r["summary"]["score"], 20)
        attempt.refresh_from_db()
        self.assertTrue(attempt.premature_finish)

    def test_cu01_fa1_reset_clears_log(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, rounds=3)
        self.post(f"/elicitacion/api/intento/{attempt.id}/reiniciar/")
        self.assertEqual(attempt.log_entries.count(), 0)
        r = self.client.get(f"/elicitacion/intento/{attempt.id}/")
        self.assertEqual(r.context["progress"]["asked"], 0)

    def test_finished_interview_page_shows_summary(self):
        attempt = self.finished_attempt()
        r = self.client.get(f"/elicitacion/intento/{attempt.id}/")
        self.assertContains(r, "90</b> / 90 pts")
        self.assertContains(r, "Entrevistador(a) experto(a)")


@override_settings(INGENIALAB_MODULES=["interviews"])
class ModuleGateTests(BaseCase):
    def test_disabled_modules_redirect_to_interviews(self):
        for url in ["/", "/modelado/", "/inspeccion/", "/reportes/"]:
            self.assertRedirects(self.client.get(url), "/elicitacion/", fetch_redirect_response=False)

    def test_disabled_module_api_returns_404(self):
        self.assertEqual(self.post("/modelado/api/generar/", {}).status_code, 404)


@ALL_MODULES
class ClassificationTests(BaseCase):
    def test_cu03_classify_feedback_and_precision(self):
        attempt = self.finished_attempt()
        rf = attempt.version.requirements.get(key="B01")
        rnf = attempt.version.requirements.get(key="B07")
        url = f"/clasificacion/api/intento/{attempt.id}/clasificar/"
        r = self.post(url, {"requirement_id": str(rf.id), "category": "RF"}).json()
        self.assertTrue(r["is_correct"])
        self.assertIn("Requisito Funcional", r["explanation"])
        r = self.post(url, {"requirement_id": str(rnf.id), "category": "RF"}).json()
        self.assertFalse(r["is_correct"])
        self.assertEqual(r["precision"], 50.0)

    def test_cu03_fa1_reclassify_without_duplicates(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B07")
        url = f"/clasificacion/api/intento/{attempt.id}/clasificar/"
        self.post(url, {"requirement_id": str(req.id), "category": "RF"})
        r = self.post(url, {"requirement_id": str(req.id), "category": "RNF"}).json()
        self.assertTrue(r["reclassified"])
        self.assertEqual(StudentClassification.objects.filter(attempt=attempt).count(), 1)
        self.assertEqual(r["precision"], 100.0)

    def test_cu03_e1_requires_valid_category(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.first()
        r = self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("RF o RNF", r.json()["message"])

    def test_cannot_classify_statement_not_in_log(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, rounds=1)
        self.post(f"/elicitacion/api/intento/{attempt.id}/finalizar/", {"confirm": True})
        other = self.version.requirements.get(key="B07")
        r = self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(other.id), "category": "RNF"})
        self.assertEqual(r.status_code, 400)

    def test_hint_penalizes_score(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id), "category": "RF"})
        r = self.post(f"/clasificacion/api/intento/{attempt.id}/pista/", {"requirement_id": str(req.id)}).json()
        self.assertEqual(r["score"], 7)


USE_CASE = {
    "name": "Registrar préstamo", "system_name": "Biblioteca",
    "primary_actors": ["Bibliotecario"], "secondary_actors": ["Servicio de correo"],
    "preconditions": "El bibliotecario inició sesión.",
    "main_flow": ["El Bibliotecario captura la matrícula.", "El sistema registra el préstamo."],
    "alternate_flows": ["FA-1: El alumno tiene 3 préstamos; el sistema rechaza."],
    "postconditions": "El préstamo queda registrado.",
    "relations": [{"type": "include", "target": "Verificar límite de préstamos"}],
}


@ALL_MODULES
class ModelingTests(BaseCase):
    def test_cu02_requires_completed_interview(self):
        r = self.client.get("/modelado/nuevo/")
        self.assertRedirects(r, "/modelado/")

    def test_cu02_e1_missing_fields_highlighted(self):
        self.finished_attempt()
        r = self.post("/modelado/api/generar/", {"name": "Registrar préstamo", "main_flow": ["uno"]})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertIn("actor principal", body["message"])
        self.assertIn("primary_actors", body["errors"])
        self.assertIn("main_flow", body["errors"])

    def test_cu02_generate_save_and_regenerate_without_duplicates(self):
        self.finished_attempt()
        r = self.post("/modelado/api/generar/", USE_CASE).json()
        self.assertTrue(r["ok"])
        self.assertIn("@startuml", r["plantuml_code"])
        self.assertIn('actor "Bibliotecario" as P1', r["plantuml_code"])
        self.assertIn("<<include>>", r["plantuml_code"])
        self.assertIn("<svg", r["svg"])
        saved = self.post("/modelado/api/guardar/", USE_CASE).json()
        changed = dict(USE_CASE, id=saved["id"], name="Registrar préstamo de libro")
        self.post("/modelado/api/guardar/", changed)
        self.assertEqual(UseCaseSpecification.objects.filter(user=self.user).count(), 1)
        uc = UseCaseSpecification.objects.get(user=self.user)
        self.assertEqual(uc.name, "Registrar préstamo de libro")
        self.assertTrue(uc.diagram.svg.startswith("<svg"))

    def test_actor_cannot_be_primary_and_secondary(self):
        self.finished_attempt()
        data = dict(USE_CASE, secondary_actors=["Bibliotecario"])
        r = self.post("/modelado/api/generar/", data)
        self.assertIn("secondary_actors", r.json()["errors"])


class PlantUMLTests(TestCase):
    def test_fallback_renderer_when_jar_missing(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(PLANTUML_ALLOW_FALLBACK=True, PLANTUML_JAR="/no/existe.jar", PLANTUML_CACHE_DIR=tmp):
            from integrations.plantuml.builder import build_usecase_diagram
            from apps.modeling.validators import normalize
            code = build_usecase_diagram(normalize(USE_CASE))
            result = plantuml.render(code)
        self.assertEqual(result.engine, "fallback")
        self.assertIn("Bibliotecario", result.svg)


@ALL_MODULES
class InspectionTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.exercise = InspectionExercise.objects.get(code="INS-CONTROL-ESCOLAR-01")
        self.client.post(f"/inspeccion/iniciar/{self.exercise.id}/")
        self.attempt = self.user.inspections.latest("started_at")
        self.base = f"/inspeccion/api/intento/{self.attempt.id}/"

    def test_cu04_correct_finding_and_conclusion(self):
        for fr in self.exercise.fragments.exclude(defect_type=""):
            r = self.post(self.base + "hallazgo/", {"fragment_id": str(fr.id), "defect_type": fr.defect_type}).json()
            self.assertEqual(r["status"], "correct")
        r = self.post(self.base + "concluir/").json()
        self.assertEqual(r["summary"]["precision"], 100.0)
        self.assertEqual(r["summary"]["score"], 60)
        names = {b["name"] for b in r["badges"]}
        self.assertIn("Ojo de auditor", names)
        self.assertIn("Sin ayuda", names)

    def test_cu04_e1_marking_correct_fragment(self):
        ok_fragment = self.exercise.fragments.filter(defect_type="").first()
        r = self.post(self.base + "hallazgo/", {"fragment_id": str(ok_fragment.id), "defect_type": "ambiguity"}).json()
        self.assertEqual(r["status"], "no_defect")
        self.assertEqual(r["message"], "El fragmento no contiene defectos conforme a la clave.")
        self.assertEqual(r["summary"]["wrong"], 1)

    def test_cu04_fa1_hint_penalty(self):
        r = self.post(self.base + "pista/").json()
        self.assertTrue(r["hint"].startswith("Revisa la sección"))
        self.assertEqual(r["summary"]["hints_used"], 1)

    def test_concluded_practice_is_locked(self):
        self.post(self.base + "concluir/")
        fr = self.exercise.fragments.first()
        r = self.post(self.base + "hallazgo/", {"fragment_id": str(fr.id), "defect_type": "ambiguity"})
        self.assertEqual(r.status_code, 400)


@ALL_MODULES
class ReportTests(BaseCase):
    def test_cu05_e1_no_data(self):
        r = self.client.get("/reportes/descargar/", follow=True)
        self.assertContains(r, "No hay actividades guardadas para generar el reporte técnico.")

    def test_cu05_download_pdf(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id), "category": "RF"})
        self.post("/modelado/api/guardar/", USE_CASE)
        r = self.client.get("/reportes/descargar/")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertRegex(r["Content-Disposition"], r'IngeniaLab_Reporte_ALUMNO-\w{6}\.pdf')
        self.assertTrue(r.content.startswith(b"%PDF"))


@ALL_MODULES
class ProgressTests(BaseCase):
    def test_dashboard_and_points(self):
        self.finished_attempt()
        r = self.client.get("/")
        self.assertContains(r, "Primera entrevista")
        self.assertContains(r, "90 puntos")
