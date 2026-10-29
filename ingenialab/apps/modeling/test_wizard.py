"""Asistente paso a paso para crear un caso de uso propio (CU-02)."""
from django.conf import settings
from django.test import override_settings

from apps.progress.tests import BaseCase


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class WizardTests(BaseCase):
    def test_requires_finished_interview(self):
        r = self.client.get("/modelado/asistente/")
        self.assertRedirects(r, "/modelado/", fetch_redirect_response=False)

    def test_page_offers_guide_and_actor_suggestions(self):
        attempt = self.finished_attempt()
        r = self.client.get(f"/modelado/asistente/?attempt={attempt.id}")
        self.assertContains(r, "usecase-wizard.js")
        self.assertContains(r, "modeling-validation.js")
        self.assertEqual(r.context["selected"], str(attempt.id))
        guide = r.context["guide"][0]
        self.assertIn("Bibliotecario", guide["actors"])
        # B04 (impedir con tres libros) es regla de «Registrar préstamo»; B01 y B02 son metas.
        self.assertIn("B04", guide["part_of"])
        self.assertNotIn("B01", guide["part_of"])
        self.assertNotIn("B02", guide["part_of"])
        self.assertEqual(r.context["validation_rules"]["min_steps"], 2)

    def test_unknown_attempt_falls_back_to_first(self):
        attempt = self.finished_attempt()
        r = self.client.get("/modelado/asistente/?attempt=no-existe")
        self.assertEqual(r.context["selected"], str(attempt.id))

    def test_modeling_list_links_wizard_and_advanced_editor(self):
        self.finished_attempt()
        r = self.client.get("/modelado/")
        self.assertContains(r, 'href="/modelado/asistente/"')
        self.assertContains(r, 'href="/modelado/lecciones/"')
        self.assertContains(r, "Editor avanzado")
