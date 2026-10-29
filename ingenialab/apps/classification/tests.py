"""Pruebas del clasificador interactivo RF/RNF (CU-03, ACT-208A).

Complementan ``ClassificationTests`` de apps/progress/tests.py verificando las garantías
de la base de datos y la persistencia visual de la bitácora.
"""
from django.db import IntegrityError, transaction

from apps.progress.tests import BaseCase

from .models import StudentClassification


class ClassifierConstraintTests(BaseCase):
    def test_db_unique_rejects_duplicate_classification(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        StudentClassification.objects.create(attempt=attempt, master_requirement=req, selected_category="RF", is_correct=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentClassification.objects.create(attempt=attempt, master_requirement=req, selected_category="RNF", is_correct=False)

    def test_db_check_rejects_category_outside_rf_rnf(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentClassification.objects.create(attempt=attempt, master_requirement=req, selected_category="AMB", is_correct=False)

    def test_api_rejects_category_outside_rf_rnf(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        r = self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id), "category": "AMB"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(StudentClassification.objects.filter(attempt=attempt).exists())

    def test_switching_category_keeps_single_exclusive_row(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        url = f"/clasificacion/api/intento/{attempt.id}/clasificar/"
        for category in ("RF", "RNF", "RF"):
            self.post(url, {"requirement_id": str(req.id), "category": category})
        row = StudentClassification.objects.get(attempt=attempt, master_requirement=req)
        self.assertEqual(row.selected_category, "RF")
        self.assertEqual(row.times_changed, 2)


class ClassifierViewTests(BaseCase):
    def test_log_statements_are_highlightable(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        self.assertContains(r, f'data-req="{req.id}"')

    def test_reload_shows_previous_classifications(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B07")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {"requirement_id": str(req.id), "category": "RNF"})
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        rows = r.context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["req_id"], str(req.id))
        self.assertEqual(rows[0]["category"], "RNF")
        self.assertContains(r, 'id="rows-data"')

    def test_interviewing_attempt_redirects_to_interview(self):
        attempt = self.new_attempt()
        r = self.client.get(f"/clasificacion/intento/{attempt.id}/")
        self.assertRedirects(r, f"/elicitacion/intento/{attempt.id}/", fetch_redirect_response=False)

    def test_other_user_cannot_open_classifier(self):
        attempt = self.finished_attempt()
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.client.get(f"/clasificacion/intento/{attempt.id}/").status_code, 404)
