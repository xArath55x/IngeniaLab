"""Pruebas de integración de inspección, reporte PDF y tablero (ACT-211A2, WP.14).

Verifican que los seis módulos estén habilitados por defecto y que CU-04, CU-05 y el tablero
operen sobre el perfil del usuario autenticado sin mezclar datos entre cuentas.
"""
import os
import runpy
from unittest import mock

from django.conf import settings
from django.test import override_settings

from apps.inspection.models import InspectionExercise
from apps.progress.models import ReportExport
from apps.progress.services import total_points

from .tests import USE_CASE, BaseCase


class DefaultModulesTests(BaseCase):
    def test_all_modules_enabled_without_env_variable(self):
        env = {k: v for k, v in os.environ.items() if k != "INGENIALAB_MODULES"}
        with mock.patch.dict(os.environ, env, clear=True):
            conf = runpy.run_path(str(settings.BASE_DIR / "config" / "settings.py"))
        self.assertEqual(conf["INGENIALAB_MODULES"], conf["ALL_MODULES"])

    def test_env_variable_still_limits_modules(self):
        with mock.patch.dict(os.environ, {"INGENIALAB_MODULES": "interviews,classification"}):
            conf = runpy.run_path(str(settings.BASE_DIR / "config" / "settings.py"))
        self.assertEqual(conf["INGENIALAB_MODULES"], ["interviews", "classification"])


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class AssemblyTests(BaseCase):
    def complete_all_activities(self):
        """CU-01 → CU-03 → modelado → CU-04 con la misma cuenta."""
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id), "category": "RF"})
        self.post("/modelado/api/guardar/", USE_CASE)
        exercise = InspectionExercise.objects.get(code="INS-CONTROL-ESCOLAR-01")
        self.client.post(f"/inspeccion/iniciar/{exercise.id}/")
        inspection = self.user.inspections.latest("started_at")
        base = f"/inspeccion/api/intento/{inspection.id}/"
        for fr in exercise.fragments.exclude(defect_type=""):
            self.post(base + "hallazgo/", {"fragment_id": str(fr.id), "defect_type": fr.defect_type})
        self.post(base + "concluir/")
        return attempt, exercise

    def test_navigation_links_every_module(self):
        r = self.client.get("/")
        for url in ("/elicitacion/", "/modelado/", "/inspeccion/", "/reportes/"):
            self.assertContains(r, f'href="{url}"')

    def test_every_module_entry_point_responds(self):
        for url in ("/", "/elicitacion/", "/modelado/", "/inspeccion/", "/reportes/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_dashboard_aggregates_all_activities_of_user(self):
        _, exercise = self.complete_all_activities()
        points = total_points(self.user)
        self.assertGreater(points, 90 + 10 + 60)
        r = self.client.get("/")
        self.assertContains(r, f"{points} puntos")
        self.assertContains(r, exercise.title)

    def test_report_includes_inspection_and_downloads_pdf(self):
        attempt, exercise = self.complete_all_activities()
        r = self.client.get("/reportes/")
        self.assertContains(r, attempt.version.title)
        self.assertContains(r, exercise.title)
        r = self.client.get("/reportes/descargar/")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertEqual(ReportExport.objects.filter(user=self.user).count(), 1)

    def test_other_user_sees_only_own_profile(self):
        _, exercise = self.complete_all_activities()
        self.client.login(username="otro", password="ClaveSegura123")
        r = self.client.get("/")
        self.assertContains(r, "0 puntos")
        self.assertNotContains(r, exercise.title)
        r = self.client.get("/reportes/descargar/", follow=True)
        self.assertContains(r, "No hay actividades guardadas para generar el reporte técnico.")
        self.assertFalse(ReportExport.objects.filter(user=self.other).exists())

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        for url in ("/", "/inspeccion/", "/reportes/", "/reportes/descargar/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/cuentas/", r["Location"])
