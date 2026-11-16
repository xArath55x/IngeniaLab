"""CU-10 · Autoguardado y reanudación (ACT-307A; SDS v3.0 §9.6)."""
import uuid
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.inspection.models import InspectionAttempt, InspectionExercise
from apps.interviews.models import StudentAttempt
from apps.progress import checkpoints
from apps.progress.models import PracticeCheckpoint
from apps.progress.services import total_points

from .tests import BaseCase

SAVE = "/api/checkpoints/"


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class CheckpointApiTests(BaseCase):
    def save(self, module, key, revision=0, payload=None, pause=False, client=None):
        body = {"module": module, "key": str(key), "revision": revision,
                "payload": {"name": "Borrador"} if payload is None else payload, "pause": pause}
        return self.post(SAVE, body) if client is None else client.post(SAVE, body, content_type="application/json")

    def test_save_creates_then_increments_revision_and_get_returns_payload(self):
        attempt = self.new_attempt()
        r = self.save("interview", attempt.id, payload={"round": 3})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["revision"], 1)
        r = self.save("interview", attempt.id, revision=1, payload={"round": 4}, pause=True)
        self.assertEqual(r.json()["revision"], 2)
        self.assertTrue(r.json()["paused"])
        data = self.client.get(f"{SAVE}interview/{attempt.id}/").json()
        self.assertTrue(data["found"])
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["payload"], {"round": 4, "schema": 1})
        self.assertTrue(data["paused"])
        self.assertEqual(PracticeCheckpoint.objects.count(), 1)

    def test_title_names_the_practice(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        self.assertEqual(PracticeCheckpoint.objects.get().title, f"Entrevista · {self.version.title}")

    def test_new_use_case_draft_uses_nuevo_key_and_draft_name(self):
        key = f"nuevo:{uuid.uuid4()}"
        r = self.save("modeling", key, payload={"name": "Registrar préstamo"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PracticeCheckpoint.objects.get().title, "Caso de uso · Registrar préstamo")

    def test_api_without_session_returns_401_json(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        self.client.logout()
        for response in (self.save("interview", attempt.id, revision=1),
                         self.client.get(f"{SAVE}interview/{attempt.id}/"),
                         self.post(f"{SAVE}interview/{attempt.id}/descartar/")):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response["Content-Type"], "application/json")
            self.assertEqual(response.json()["error"], "session_expired")
        self.assertEqual(PracticeCheckpoint.objects.get().revision, 1)

    def test_other_users_practice_is_404(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        self.client.logout()
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.save("interview", attempt.id).status_code, 404)
        self.assertEqual(self.client.get(f"{SAVE}interview/{attempt.id}/").status_code, 404)
        self.assertEqual(self.post(f"{SAVE}interview/{attempt.id}/descartar/").status_code, 404)
        self.assertEqual(PracticeCheckpoint.objects.filter(user=self.other).count(), 0)
        self.assertTrue(PracticeCheckpoint.objects.filter(user=self.user).exists())

    def test_stale_revision_is_409_and_keeps_saved_data(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id, payload={"round": 1})
        self.save("interview", attempt.id, revision=1, payload={"round": 2})
        r = self.save("interview", attempt.id, revision=1, payload={"round": 9})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "revision_conflict")
        self.assertEqual(r.json()["server_revision"], 2)
        cp = PracticeCheckpoint.objects.get()
        self.assertEqual((cp.revision, cp.payload["round"]), (2, 2))

    def test_new_save_over_existing_checkpoint_is_409(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        r = self.save("interview", attempt.id, revision=0)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["server_revision"], 1)

    def test_revision_without_checkpoint_is_409(self):
        attempt = self.new_attempt()
        r = self.save("interview", attempt.id, revision=3)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["server_revision"], 0)

    def test_finished_interview_rejects_and_deletes_checkpoint(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        self.ask_rounds(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, StudentAttempt.CLASSIFYING)
        r = self.save("interview", attempt.id, revision=1)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "practice_closed")
        self.assertFalse(PracticeCheckpoint.objects.exists())

    def test_get_of_closed_practice_reports_nothing_and_cleans_up(self):
        exercise = InspectionExercise.objects.filter(is_active=True).first()
        attempt = InspectionAttempt.objects.create(user=self.user, exercise=exercise)
        self.save("inspection", attempt.id, payload={"fragment": "x"})
        attempt.concluded_at = timezone.now()
        attempt.save()
        r = self.client.get(f"{SAVE}inspection/{attempt.id}/")
        self.assertEqual((r.status_code, r.json()["found"]), (200, False))
        self.assertFalse(PracticeCheckpoint.objects.exists())

    def test_classification_checkpoint_needs_finished_interview(self):
        attempt = self.new_attempt()
        self.assertEqual(self.save("classification", attempt.id).json()["error"], "practice_closed")
        finished = self.finished_attempt()
        self.assertEqual(self.save("classification", finished.id).status_code, 200)

    def test_payload_over_64kb_is_413(self):
        attempt = self.new_attempt()
        r = self.save("interview", attempt.id, payload={"text": "a" * (65 * 1024)})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["error"], "payload_too_large")
        self.assertFalse(PracticeCheckpoint.objects.exists())

    def test_invalid_requests_are_400(self):
        attempt = self.new_attempt()
        cases = [
            {"module": "grades", "key": str(attempt.id), "revision": 0, "payload": {}},
            {"module": "interview", "key": "../../etc", "revision": 0, "payload": {}},
            {"module": "interview", "key": f"nuevo:{uuid.uuid4()}", "revision": 0, "payload": {}},
            {"module": "interview", "key": str(attempt.id), "revision": -1, "payload": {}},
            {"module": "interview", "key": str(attempt.id), "revision": "1", "payload": {}},
            {"module": "interview", "key": str(attempt.id), "revision": 0, "payload": ["lista"]},
            {"module": "interview", "key": str(attempt.id), "revision": 0, "payload": {"schema": 2}},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.post(SAVE, body).status_code, 400)
        self.assertFalse(PracticeCheckpoint.objects.exists())

    def test_methods_are_restricted(self):
        self.assertEqual(self.client.get(SAVE).status_code, 405)
        attempt = self.new_attempt()
        self.assertEqual(self.post(f"{SAVE}interview/{attempt.id}/").status_code, 405)

    def test_discard_deletes_then_404(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        self.assertEqual(self.post(f"{SAVE}interview/{attempt.id}/descartar/").status_code, 200)
        self.assertEqual(self.post(f"{SAVE}interview/{attempt.id}/descartar/").status_code, 404)
        r = self.client.get(f"{SAVE}interview/{attempt.id}/")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "found": False}))

    def test_payload_never_changes_points(self):
        attempt = self.finished_attempt()
        before = total_points(self.user)
        self.save("classification", attempt.id,
                  payload={"score": 9999, "classification_score": 9999, "hints_used": 0, "points": 9999})
        self.assertEqual(total_points(self.user), before)

    def test_modules_have_separate_checkpoints(self):
        attempt = self.finished_attempt()
        lesson_key = uuid.uuid4()
        self.assertEqual(self.save("classification", attempt.id).status_code, 200)
        self.assertEqual(self.save("lesson", lesson_key).status_code, 404)
        self.assertEqual(PracticeCheckpoint.objects.count(), 1)


class CheckpointPurgeTests(BaseCase):
    def make(self, days_old):
        cp = PracticeCheckpoint.objects.create(user=self.user, module="modeling", key=f"nuevo:{uuid.uuid4()}",
                                               payload={"schema": 1})
        PracticeCheckpoint.objects.filter(pk=cp.pk).update(updated_at=timezone.now() - timedelta(days=days_old))
        return cp

    def test_purge_only_deletes_checkpoints_older_than_90_days(self):
        old, recent = self.make(91), self.make(89)
        self.assertEqual(checkpoints.purge(), 1)
        self.assertFalse(PracticeCheckpoint.objects.filter(pk=old.pk).exists())
        self.assertTrue(PracticeCheckpoint.objects.filter(pk=recent.pk).exists())

    def test_purge_command(self):
        self.make(10)
        out = StringIO()
        call_command("purge_checkpoints", "--days", "7", stdout=out)
        self.assertIn("Autoguardados borrados: 1", out.getvalue())
        self.assertFalse(PracticeCheckpoint.objects.exists())
