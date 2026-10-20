import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import services
from .models import InspectionAttempt, InspectionExercise, InspectionFragment


class InspectionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user("alumno", password="x12345678")
        cls.other = User.objects.create_user("otro", password="x12345678")
        cls.ex = InspectionExercise.objects.create(code="T-01", title="Ejercicio", description="d")
        mk = lambda order, label, dt="": InspectionFragment.objects.create(
            exercise=cls.ex, order=order, label=label, text=f"texto {label}",
            defect_type=dt, explanation=f"expl {label}", hint=f"pista {label}" if dt else "")
        cls.ok = mk(1, "RF-01")
        cls.amb = mk(2, "RF-02", "ambiguity")
        cls.red = mk(3, "RF-03", "redundancy")

    def setUp(self):
        self.attempt = InspectionAttempt.objects.create(user=self.user, exercise=self.ex)

    def refresh(self):
        self.attempt.refresh_from_db()
        return self.attempt


class AuditEngineTests(InspectionBase):
    def test_acierto_suma_y_da_retroalimentacion(self):
        r = services.register_finding(self.attempt, self.amb.id, "ambiguity")
        self.assertEqual(r["status"], "correct")
        self.assertIn("expl RF-02", r["explanation"])
        self.assertEqual(r["summary"]["found"], 1)
        self.assertEqual(r["summary"]["precision"], 100.0)
        self.assertEqual(r["summary"]["score"], 10)

    def test_tipo_equivocado_penaliza(self):
        r = services.register_finding(self.attempt, self.amb.id, "redundancy")
        self.assertEqual(r["status"], "wrong_type")
        self.assertEqual(self.refresh().wrong_registrations, 1)
        self.assertEqual(r["summary"]["found"], 0)

    def test_fragmento_correcto_marcado_como_defecto(self):  # E-1
        r = services.register_finding(self.attempt, self.ok.id, "ambiguity")
        self.assertEqual(r["status"], "no_defect")
        self.assertEqual(self.refresh().wrong_registrations, 1)
        self.assertFalse(self.attempt.findings.exists())

    def test_tipo_invalido_y_fragmento_inexistente(self):
        with self.assertRaises(services.AuditError):
            services.register_finding(self.attempt, self.amb.id, "inventado")
        with self.assertRaises(services.AuditError):
            services.register_finding(self.attempt, uuid.uuid4(), "ambiguity")
        with self.assertRaises(services.AuditError):
            services.register_finding(self.attempt, None, "ambiguity")
        self.assertEqual(self.refresh().registrations, 0)

    # Regresión: un fragment_id mal formado debe dar AuditError (antes: ValidationError -> 500)
    def test_fragment_id_mal_formado_da_error_controlado(self):
        with self.assertRaises(services.AuditError):
            services.register_finding(self.attempt, "no-es-uuid", "ambiguity")

    def test_formula_precision_y_puntaje(self):
        services.register_finding(self.attempt, self.amb.id, "ambiguity")   # +10
        services.register_finding(self.attempt, self.red.id, "ambiguity")   # error -3
        services.register_finding(self.attempt, self.ok.id, "ambiguity")    # error -3
        services.request_hint(self.attempt)                                 # pista -5
        s = services.summary(self.refresh())
        self.assertEqual(s["precision"], 33.3)  # 1 acierto / 3 registros
        self.assertEqual(s["score"], 0)         # 10 - 6 - 5 = -1 -> piso en 0

    def test_pista_apunta_al_primer_defecto_pendiente_y_cuesta(self):
        r = services.request_hint(self.attempt)
        self.assertEqual(r["fragment_id"], str(self.amb.id))
        self.assertIn("RF-02", r["hint"])
        self.assertEqual(self.refresh().hints_used, 1)
        services.register_finding(self.attempt, self.amb.id, "ambiguity")
        r = services.request_hint(self.attempt)
        self.assertEqual(r["fragment_id"], str(self.red.id))

    def test_sin_pendientes_no_cobra_pista(self):
        services.register_finding(self.attempt, self.amb.id, "ambiguity")
        services.register_finding(self.attempt, self.red.id, "redundancy")
        r = services.request_hint(self.attempt)
        self.assertIsNone(r["fragment_id"])
        self.assertEqual(self.refresh().hints_used, 0)

    def test_concluir_persiste_y_bloquea_cambios(self):
        services.register_finding(self.attempt, self.amb.id, "ambiguity")
        s = services.conclude(self.attempt)
        self.assertEqual(s["score"], 10)
        self.assertTrue(self.refresh().is_concluded)
        for fn in (lambda: services.register_finding(self.attempt, self.red.id, "redundancy"),
                   lambda: services.request_hint(self.attempt),
                   lambda: services.conclude(self.attempt)):
            with self.assertRaises(services.AuditError):
                fn()

    def test_defect_count_ignora_fragmentos_correctos(self):
        self.assertEqual(self.ex.defect_count, 2)

    # Regresión: un acierto no debe perderse si se reintenta el fragmento con otro tipo
    def test_hallazgo_correcto_no_se_pierde_si_se_reintenta_con_otro_tipo(self):
        services.register_finding(self.attempt, self.amb.id, "ambiguity")
        services.register_finding(self.attempt, self.amb.id, "redundancy")
        self.assertEqual(services.summary(self.refresh())["found"], 1)


@override_settings(INGENIALAB_MODULES=["interviews", "classification", "modeling", "inspection", "reports", "progress"])
class InspectionApiTests(InspectionBase):
    def _post(self, name, attempt, data=None):
        url = reverse(f"inspection:{name}", args=[attempt.id])
        return self.client.post(url, json.dumps(data or {}), content_type="application/json")

    def test_api_sin_sesion_devuelve_401_json(self):
        r = self._post("api_hint", self.attempt)
        self.assertEqual(r.status_code, 401)

    def test_flujo_completo_por_api(self):
        self.client.force_login(self.user)
        r = self._post("api_finding", self.attempt, {"fragment_id": str(self.amb.id), "defect_type": "ambiguity"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "correct")
        r = self._post("api_conclude", self.attempt)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["summary"]["found"], 1)

    def test_no_se_puede_operar_intento_ajeno(self):
        self.client.force_login(self.other)
        self.assertEqual(self._post("api_hint", self.attempt).status_code, 404)

    def test_error_de_dominio_devuelve_mensaje(self):
        self.client.force_login(self.user)
        r = self._post("api_finding", self.attempt, {"fragment_id": str(self.amb.id), "defect_type": "x"})
        self.assertGreaterEqual(r.status_code, 400)
        self.assertLess(r.status_code, 500)

    def test_iniciar_crea_intento_y_redirige(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("inspection:start", args=[self.ex.id]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(InspectionAttempt.objects.filter(user=self.user).count(), 2)
