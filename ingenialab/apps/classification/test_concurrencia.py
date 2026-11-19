"""Pistas y clasificaciones con un intento desactualizado (ACT-313B; OBS-05)."""
from apps.interviews.models import StudentAttempt
from apps.progress.tests import BaseCase

from . import services


class StaleAttemptTests(BaseCase):
    def test_two_hints_from_stale_copies_charge_both(self):
        attempt = self.finished_attempt()
        req = services.available_requirements(attempt).first()
        first, second = StudentAttempt.objects.get(pk=attempt.pk), StudentAttempt.objects.get(pk=attempt.pk)
        services.request_hint(first, req.id)
        services.request_hint(second, req.id)
        attempt.refresh_from_db()
        self.assertEqual(attempt.hints_used, 2)

    def test_score_counts_hint_taken_by_another_request(self):
        attempt = self.finished_attempt()
        req = services.available_requirements(attempt).first()
        stale = StudentAttempt.objects.get(pk=attempt.pk)
        services.request_hint(attempt, req.id)
        r = services.classify_statement(stale, req.id, req.expected_type)
        self.assertEqual(r.score, services.POINTS_PER_CORRECT - services.HINT_PENALTY)


class HintOutsideClassificationTests(BaseCase):  # Revisión del PR #48
    def test_hint_is_rejected_and_not_charged_while_interviewing(self):
        attempt = self.new_attempt()
        req = attempt.version.requirements.first()
        with self.assertRaises(services.ClassificationError):
            services.request_hint(attempt, req.id)
        attempt.refresh_from_db()
        self.assertEqual(attempt.hints_used, 0)
