"""Pruebas de la retroalimentación pedagógica inmediata (CU-03, ACT-208B).

Verifican la comparación contra MasterRequirement, el cálculo de precisión formativa,
las explicaciones (feedback_explanation) y la persistencia en student_classifications.
"""
from apps.interviews.models import MasterRequirement
from apps.progress.tests import BaseCase

from . import services
from .models import StudentClassification


def _other(category):
    return MasterRequirement.RNF if category == MasterRequirement.RF else MasterRequirement.RF


class FeedbackTests(BaseCase):
    def classify(self, attempt, req, category):
        return self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                         {"requirement_id": str(req.id), "category": category}).json()

    def test_every_seeded_requirement_has_feedback_explanation(self):
        empty = MasterRequirement.objects.filter(feedback_explanation__regex=r"^\s*$")
        self.assertFalse(empty.exists(), list(empty.values_list("key", flat=True)))

    def test_compares_against_expected_type_of_master_requirement(self):
        attempt = self.finished_attempt()
        for req in services.available_requirements(attempt):
            r = self.classify(attempt, req, _other(req.expected_type))
            self.assertFalse(r["is_correct"], req.key)
            r = self.classify(attempt, req, req.expected_type)
            self.assertTrue(r["is_correct"], req.key)
        self.assertEqual(r["precision"], 100.0)

    def test_feedback_card_returns_explanation_for_correct_and_wrong(self):
        attempt = self.finished_attempt()
        rf = attempt.version.requirements.get(key="B01")
        rnf = attempt.version.requirements.get(key="B07")
        self.assertEqual(self.classify(attempt, rf, "RF")["explanation"], rf.feedback_explanation)
        self.assertEqual(self.classify(attempt, rnf, "RF")["explanation"], rnf.feedback_explanation)

    def test_precision_is_correct_over_classified_and_persisted(self):
        attempt = self.finished_attempt()
        reqs = list(services.available_requirements(attempt)[:4])
        self.assertEqual(len(reqs), 4)
        for req in reqs[:3]:
            self.classify(attempt, req, req.expected_type)
        r = self.classify(attempt, reqs[3], _other(reqs[3].expected_type))
        self.assertEqual(r["precision"], 75.0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.classification_precision, 75.0)
        self.assertEqual(attempt.classification_score, 30)

    def test_reclassification_updates_precision_and_persisted_row(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B07")
        self.assertEqual(self.classify(attempt, req, _other(req.expected_type))["precision"], 0.0)
        row = StudentClassification.objects.get(attempt=attempt, master_requirement=req)
        self.assertFalse(row.is_correct)
        r = self.classify(attempt, req, req.expected_type)
        self.assertEqual(r["precision"], 100.0)
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(row.selected_category, req.expected_type)

    def test_rows_reflect_persisted_result(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        rows = self.classify(attempt, req, req.expected_type)["rows"]
        self.assertEqual(rows, [{"req_id": str(req.id), "statement": req.statement_text,
                                 "category": req.expected_type, "is_correct": True}])
        self.assertEqual(StudentClassification._meta.db_table, "student_classifications")

    def test_score_never_negative_with_hints(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        for _ in range(2):
            self.post(f"/clasificacion/api/intento/{attempt.id}/pista/", {"requirement_id": str(req.id)})
        attempt.refresh_from_db()
        self.assertEqual(attempt.classification_score, 0)
        self.assertEqual(self.classify(attempt, req, req.expected_type)["score"], 4)

    def test_precision_is_zero_without_classifications(self):
        attempt = self.finished_attempt()
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        self.assertContains(r, '<b id="m-precision">0.0 %</b>', html=False)

    def test_cannot_classify_before_finishing_interview(self):
        attempt = self.new_attempt()
        self.ask_rounds(attempt, rounds=1)
        req = attempt.version.requirements.get(key="B01")
        r = self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": "RF"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(StudentClassification.objects.filter(attempt=attempt).exists())
