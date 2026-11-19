"""Sugerencia de consistencia entre actores y flujo principal (ACT-313B; OBS-02)."""
from django.test import TestCase

from apps.modeling import validators
from apps.modeling.models import ReferenceUseCase
from apps.progress.tests import BaseCase

CONSISTENCY = "Consistencia: el flujo principal no menciona a ningún actor principal."


def spec(actor, *steps):
    return {"name": "Registrar préstamo", "primary_actors": [actor], "main_flow": list(steps),
            "alternate_flows": ["FA-1: algo"]}


class ActorMentionTests(TestCase):
    def test_actor_named_by_its_head_noun_counts(self):
        s = spec("Coordinadora de la biblioteca", "La coordinadora elige el mes.", "El sistema genera el reporte.")
        self.assertNotIn(CONSISTENCY, validators.suggestions(s))

    def test_full_name_still_counts(self):
        s = spec("Bibliotecario", "El bibliotecario captura la matrícula.", "El sistema muestra los préstamos.")
        self.assertNotIn(CONSISTENCY, validators.suggestions(s))

    def test_missing_actor_still_warns(self):
        s = spec("Bibliotecario", "El alumno captura la matrícula.", "El sistema muestra los préstamos.")
        self.assertIn(CONSISTENCY, validators.suggestions(s))

    def test_generic_head_does_not_hide_missing_external_system(self):
        s = spec("Sistema de pagos", "El alumno paga.", "El sistema confirma el pago.")
        self.assertIn(CONSISTENCY, validators.suggestions(s))

    def test_leading_adjective_is_not_the_head_noun(self):  # Revisión del PR #48
        s = spec("Nuevo cliente", "El alumno crea un nuevo registro.", "El sistema guarda el registro.")
        self.assertIn(CONSISTENCY, validators.suggestions(s))
        s = spec("Nuevo cliente", "El cliente llena el formulario.", "El sistema guarda el registro.")
        self.assertNotIn(CONSISTENCY, validators.suggestions(s))

    def test_plural_head_noun_counts(self):  # Revisión del PR #48
        s = spec("Coordinadora de la biblioteca", "Las coordinadoras eligen el mes.", "El sistema genera el reporte.")
        self.assertNotIn(CONSISTENCY, validators.suggestions(s))
        s = spec("Tutor asignado", "Los tutores revisan la cita.", "El sistema confirma.")
        self.assertNotIn(CONSISTENCY, validators.suggestions(s))

    def test_head_noun_must_be_a_whole_word(self):
        s = spec("Encargado de la cafetería", "El encargadote revisa.", "El sistema avisa.")
        self.assertIn(CONSISTENCY, validators.suggestions(s))


class ReferenceUseCaseTests(BaseCase):
    def test_no_reference_use_case_gets_false_consistency_warning(self):
        flagged = [r.key for r in ReferenceUseCase.objects.all() if CONSISTENCY in validators.suggestions(r.spec)]
        self.assertEqual(flagged, [])
        self.assertGreaterEqual(ReferenceUseCase.objects.count(), 14)
