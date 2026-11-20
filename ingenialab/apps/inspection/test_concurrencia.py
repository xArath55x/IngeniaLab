"""Registros simultáneos en la misma inspección (ACT-313B; OBS-05 de la Matriz de Compatibilidad).

Cada petición carga el intento antes de abrir la transacción. Si dos llegan a la vez, ambas parten del
mismo contador; las pruebas simulan esa situación con dos copias del mismo intento.
"""
from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase

from . import services
from .models import InspectionAttempt
from .tests import InspectionBase


class StaleAttemptTests(InspectionBase):
    def stale_pair(self):
        return InspectionAttempt.objects.get(pk=self.attempt.pk), InspectionAttempt.objects.get(pk=self.attempt.pk)

    def test_two_registrations_from_stale_copies_count_both(self):
        first, second = self.stale_pair()
        services.register_finding(first, self.amb.id, "ambiguity")
        r = services.register_finding(second, self.ok.id, "ambiguity")  # `second` no vio el primer registro
        attempt = self.refresh()
        self.assertEqual((attempt.registrations, attempt.wrong_registrations), (2, 1))
        self.assertEqual(r["summary"]["found"], 1)
        self.assertEqual(second.registrations, 2)  # el objeto recibido queda al día

    def test_two_hints_from_stale_copies_charge_both(self):
        first, second = self.stale_pair()
        services.request_hint(first)
        services.request_hint(second)
        self.assertEqual(self.refresh().hints_used, 2)

    def test_conclude_uses_registrations_saved_by_another_request(self):
        stale = InspectionAttempt.objects.get(pk=self.attempt.pk)
        services.register_finding(self.attempt, self.amb.id, "ambiguity")
        services.register_finding(self.attempt, self.ok.id, "ambiguity")
        summary = services.conclude(stale)
        self.assertEqual(summary["precision"], 50.0)
        attempt = self.refresh()
        self.assertEqual((attempt.registrations, attempt.wrong_registrations), (2, 1))

    def test_registration_on_attempt_concluded_by_another_request_is_rejected(self):
        stale = InspectionAttempt.objects.get(pk=self.attempt.pk)
        services.register_finding(self.attempt, self.red.id, "redundancy")
        services.conclude(self.attempt)
        with self.assertRaises(services.AuditError):
            services.register_finding(stale, self.amb.id, "ambiguity")


class LockKeepsLoadedRelationsTests(InspectionBase):  # Revisión del PR #48
    def test_lock_does_not_drop_the_exercise_loaded_by_the_view(self):
        attempt = InspectionAttempt.objects.select_related("exercise").get(pk=self.attempt.pk)
        services.request_hint(attempt)
        with self.assertNumQueries(0):
            self.assertEqual(attempt.exercise.title, "Ejercicio")


class SqliteTransactionModeTests(SimpleTestCase):
    def test_sqlite_takes_write_lock_at_begin_and_waits(self):
        if connection.vendor != "sqlite":
            self.skipTest("Solo aplica a SQLite.")
        options = settings.DATABASES["default"]["OPTIONS"]
        self.assertEqual(options["transaction_mode"], "IMMEDIATE")
        self.assertGreaterEqual(options["timeout"], 5)
