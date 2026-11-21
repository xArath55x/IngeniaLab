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

    def test_discard_deletes_and_is_idempotent(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        r = self.post(f"{SAVE}interview/{attempt.id}/descartar/")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "discarded": True}))
        # Sin borrador: 200 y no 404, para no dejar un error en la consola (ACT-313B).
        r = self.post(f"{SAVE}interview/{attempt.id}/descartar/")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "discarded": False}))
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


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class CheckpointResumeTests(BaseCase):
    """ACT-307B: «Guardar y pausar», indicador y reanudación desde el tablero (SDS v3.0 §9.4–9.5)."""

    def save(self, module, key, payload=None, pause=False, revision=0):
        return self.post(SAVE, {"module": module, "key": str(key), "revision": revision,
                                "payload": payload or {}, "pause": pause})

    def test_practice_pages_show_autosave_bar_and_script(self):
        attempt = self.new_attempt()
        finished = self.finished_attempt()
        exercise = InspectionExercise.objects.filter(is_active=True).first()
        inspection = InspectionAttempt.objects.create(user=self.user, exercise=exercise)
        pages = [f"/elicitacion/intento/{attempt.id}/", f"/clasificacion/intento/{finished.id}/",
                 f"/inspeccion/intento/{inspection.id}/", "/modelado/nuevo/"]
        for url in pages:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, "data-autosave")
                self.assertContains(r, "Guardar y pausar")
                self.assertContains(r, "js/autosave.js")

    def test_lesson_page_shows_bar_while_in_progress(self):
        from apps.classification.services import available_requirements
        from apps.modeling.models import ReferenceUseCase, UseCaseLesson
        attempt = self.finished_attempt()
        for req in available_requirements(attempt):
            self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                      {"requirement_id": str(req.id), "category": req.expected_type})
        ref = ReferenceUseCase.objects.filter(version=self.version).first()
        self.client.post(f"/modelado/lecciones/{ref.id}/iniciar/", {"attempt": str(attempt.id)})
        lesson = UseCaseLesson.objects.get(user=self.user, reference=ref)
        r = self.client.get(f"/modelado/leccion/{lesson.id}/")
        self.assertContains(r, "data-autosave")
        self.assertContains(r, f'key: "{lesson.id}"')
        lesson.status = UseCaseLesson.COMPLETED
        lesson.save()
        self.assertNotContains(self.client.get(f"/modelado/leccion/{lesson.id}/"), "data-autosave")

    def test_closed_practices_do_not_show_the_bar(self):
        finished = self.finished_attempt()
        r = self.client.get(f"/elicitacion/intento/{finished.id}/")
        self.assertNotContains(r, "data-autosave")
        exercise = InspectionExercise.objects.filter(is_active=True).first()
        done = InspectionAttempt.objects.create(user=self.user, exercise=exercise, concluded_at=timezone.now())
        self.assertNotContains(self.client.get(f"/inspeccion/intento/{done.id}/"), "data-autosave")

    def test_dashboard_lists_new_use_case_draft_with_server_side_resume_link(self):
        key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", key, payload={"name": "Registrar préstamo", "url": "https://malicioso.example"}, pause=True)
        r = self.client.get("/")
        self.assertContains(r, "Caso de uso sin guardar")
        self.assertContains(r, "Registrar préstamo")
        self.assertContains(r, f'href="/modelado/nuevo/?borrador={key}"')
        self.assertContains(r, "⏸ Pausada")
        self.assertNotContains(r, "malicioso.example")

    def test_dashboard_marks_paused_interview(self):
        attempt = self.new_attempt()
        r = self.client.get("/")
        self.assertNotContains(r, "⏸ Pausada")
        self.save("interview", attempt.id, pause=True)
        r = self.client.get("/")
        self.assertContains(r, "⏸ Pausada")
        self.assertContains(r, "autoguardado")

    def test_dashboard_drops_checkpoints_of_closed_or_deleted_practices(self):
        attempt = self.new_attempt()
        self.save("interview", attempt.id, pause=True)
        uc_key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", uc_key)
        self.ask_rounds(attempt)  # La entrevista termina: su autoguardado ya no aplica (RN-01).
        PracticeCheckpoint.objects.create(user=self.user, module="modeling", key=str(uuid.uuid4()),
                                          payload={"schema": 1})  # Caso de uso que ya no existe.
        # El tablero no los muestra, pero un GET no escribe en la BD: `close` y `purge` los borran (RN-01, RN-03).
        index, drafts = checkpoints.for_dashboard(self.user)
        self.assertEqual(list(index), [("modeling", uc_key)])
        self.assertEqual(PracticeCheckpoint.objects.count(), 2)

    def test_dashboard_does_not_show_other_users_drafts(self):
        PracticeCheckpoint.objects.create(user=self.other, module="modeling", key=f"nuevo:{uuid.uuid4()}",
                                          payload={"schema": 1}, title="Caso de uso · Ajeno")
        self.assertNotContains(self.client.get("/"), "Ajeno")

    def test_discard_from_dashboard(self):
        key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", key)
        r = self.client.post(f"/autoguardado/modeling/{key}/descartar/")
        self.assertRedirects(r, "/")
        self.assertFalse(PracticeCheckpoint.objects.exists())
        r = self.client.post(f"/autoguardado/modeling/{key}/descartar/", follow=True)
        self.assertContains(r, "Ese borrador ya no existe.")

    def test_discard_from_dashboard_requires_post_and_session(self):
        key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", key)
        self.assertEqual(self.client.get(f"/autoguardado/modeling/{key}/descartar/").status_code, 405)
        self.client.logout()
        r = self.client.post(f"/autoguardado/modeling/{key}/descartar/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cuentas/login/", r["Location"])
        self.assertTrue(PracticeCheckpoint.objects.exists())

    def test_existing_use_case_draft_resumes_in_its_editor(self):
        from apps.modeling.models import UseCaseSpecification
        uc = UseCaseSpecification.objects.create(
            user=self.user, name="Original", preconditions="a", postconditions="b",
            actors={"primary": ["Bibliotecario"], "secondary": []}, main_flow=["Uno", "Dos"], plantuml_code="@startuml\n@enduml")
        self.save("modeling", uc.id, payload={"name": "Cambiado"})
        saved, drafts = checkpoints.for_dashboard(self.user)
        self.assertEqual(drafts, [])  # Ya tiene registro propio: no es un «caso de uso sin guardar».
        cp = saved[("modeling", str(uc.id))]
        self.assertEqual(cp.resume_url, f"/modelado/{uc.id}/")
        self.assertEqual(cp.title, "Caso de uso · Cambiado")


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES)
class CheckpointReviewFixesTests(BaseCase):
    """Correcciones de la revisión del PR de ACT-307A."""

    def save(self, module, key, payload=None, revision=0):
        return self.post(SAVE, {"module": module, "key": str(key), "revision": revision, "payload": payload or {}})

    def test_long_titles_fit_the_column(self):  # Rev. 4
        self.version.title = "T" * 200
        self.version.save()
        attempt = self.new_attempt()
        self.assertEqual(self.save("interview", attempt.id).status_code, 200)
        title = PracticeCheckpoint.objects.get().title
        self.assertEqual(len(title), PracticeCheckpoint._meta.get_field("title").max_length)
        self.assertTrue(title.startswith("Entrevista · TTT") and title.endswith("…"))
        r = self.save("modeling", f"nuevo:{uuid.uuid4()}", payload={"name": "N" * 500})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(max(len(t) for t in PracticeCheckpoint.objects.values_list("title", flat=True)), 200)

    def test_new_use_case_drafts_are_limited_per_user(self):  # Rev. 7
        for _ in range(checkpoints.MAX_NEW_DRAFTS):
            self.assertEqual(self.save("modeling", f"nuevo:{uuid.uuid4()}").status_code, 200)
        r = self.save("modeling", f"nuevo:{uuid.uuid4()}")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "too_many_drafts")
        self.assertEqual(PracticeCheckpoint.objects.filter(user=self.user).count(), checkpoints.MAX_NEW_DRAFTS)
        # Actualizar uno existente sigue permitido, y otro usuario tiene su propio límite.
        key = PracticeCheckpoint.objects.first().key
        self.assertEqual(self.save("modeling", key, revision=1).status_code, 200)
        self.client.logout()
        self.client.login(username="otro", password="ClaveSegura123")
        self.assertEqual(self.save("modeling", f"nuevo:{uuid.uuid4()}").status_code, 200)

    def test_new_use_case_editor_reuses_latest_draft_key(self):  # Rev. 2
        self.finished_attempt()
        r = self.client.get("/modelado/nuevo/")
        self.assertContains(r, 'data-draft-key=""')
        old, recent = f"nuevo:{uuid.uuid4()}", f"nuevo:{uuid.uuid4()}"
        self.save("modeling", old)
        self.save("modeling", recent)
        r = self.client.get("/modelado/nuevo/")
        self.assertContains(r, f'data-draft-key="{recent}"')
        # Elegir otra entrevista o venir de una lección abre un caso limpio.
        attempt = StudentAttempt.objects.filter(user=self.user, status=StudentAttempt.CLASSIFYING).first()
        self.assertContains(self.client.get(f"/modelado/nuevo/?attempt={attempt.id}"), 'data-draft-key=""')

    def test_other_users_draft_key_is_never_offered(self):  # Rev. 2
        self.finished_attempt()
        PracticeCheckpoint.objects.create(user=self.other, module="modeling", key=f"nuevo:{uuid.uuid4()}",
                                          payload={"schema": 1})
        self.assertContains(self.client.get("/modelado/nuevo/"), 'data-draft-key=""')


class CheckpointPr43ReviewTests(BaseCase):
    """Correcciones de la revisión del PR #43 (ACT-307B)."""

    def save(self, module, key, payload=None, revision=0, pause=False):
        return self.post(SAVE, {"module": module, "key": str(key), "revision": revision,
                                "payload": payload or {}, "pause": pause})

    def make_use_case(self, name="Original"):
        from apps.modeling.models import UseCaseSpecification
        return UseCaseSpecification.objects.create(
            user=self.user, name=name, preconditions="a", postconditions="b",
            actors={"primary": ["Bibliotecario"], "secondary": []}, main_flow=["Uno", "Dos"],
            plantuml_code="@startuml\n@enduml")

    def test_attempt_editor_reuses_its_own_draft_instead_of_leaving_orphans(self):  # Hallazgo 1
        attempt = self.finished_attempt()
        url = f"/modelado/nuevo/?attempt={attempt.id}"
        self.assertContains(self.client.get(url), 'data-draft-key=""')
        mine, other, lesson = f"nuevo:{uuid.uuid4()}", f"nuevo:{uuid.uuid4()}", f"nuevo:{uuid.uuid4()}"
        self.save("modeling", mine, payload={"attempt_id": str(attempt.id)})
        self.save("modeling", other, payload={"attempt_id": str(uuid.uuid4())})
        self.save("modeling", lesson, payload={"attempt_id": str(attempt.id), "lesson_id": str(uuid.uuid4())})
        self.assertContains(self.client.get(url), f'data-draft-key="{mine}"')

    def test_lesson_draft_key_only_matches_that_lesson(self):  # Hallazgo 1
        lesson_id = uuid.uuid4()
        self.assertEqual(checkpoints.latest_new_draft_key(self.user, lesson_id=lesson_id), "")
        key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", f"nuevo:{uuid.uuid4()}", payload={"lesson_id": str(uuid.uuid4())})
        self.save("modeling", key, payload={"lesson_id": str(lesson_id)})
        self.save("modeling", f"nuevo:{uuid.uuid4()}", payload={})
        self.assertEqual(checkpoints.latest_new_draft_key(self.user, lesson_id=lesson_id), key)

    def test_saved_use_case_with_autosave_is_not_listed_as_unsaved(self):  # Hallazgo 7
        uc = self.make_use_case()
        self.save("modeling", uc.id, payload={"name": "Cambiado"})
        r = self.client.get("/")
        self.assertNotContains(r, "Caso de uso sin guardar")
        self.assertContains(r, "Cambios sin guardar")

    def test_dashboard_does_not_query_once_per_checkpoint(self):  # Hallazgo 8
        for _ in range(3):
            self.save("interview", self.new_attempt().id)
        for _ in range(3):
            self.save("modeling", self.make_use_case().id)
        self.save("modeling", f"nuevo:{uuid.uuid4()}")
        with self.assertNumQueries(3):  # Puntos de guardado + una consulta por módulo.
            index, drafts = checkpoints.for_dashboard(self.user)
        self.assertEqual((len(index), len(drafts)), (7, 1))

    def test_closing_a_practice_deletes_its_checkpoint(self):  # Hallazgo 8
        attempt = self.new_attempt()
        self.save("interview", attempt.id, pause=True)
        self.ask_rounds(attempt)
        self.assertFalse(PracticeCheckpoint.objects.filter(module="interview").exists())
        exercise = InspectionExercise.objects.filter(is_active=True).first()
        inspection = InspectionAttempt.objects.create(user=self.user, exercise=exercise)
        self.save("inspection", inspection.id)
        from apps.inspection.services import conclude, register_finding
        register_finding(inspection, exercise.fragments.first().id, "ambiguity")
        conclude(inspection)
        self.assertFalse(PracticeCheckpoint.objects.filter(module="inspection").exists())

    def test_draft_limit_locks_the_user_row(self):  # Hallazgo 9
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.save("modeling", f"nuevo:{uuid.uuid4()}").status_code, 200)
        user_table = self.user._meta.db_table
        self.assertTrue(any(user_table in q["sql"] and "FOR UPDATE" in q["sql"].upper() for q in queries)
                        or not connection.features.has_select_for_update)


@override_settings(INGENIALAB_MODULES=settings.ALL_MODULES, PLANTUML_ALLOW_FALLBACK=True, PLANTUML_JAR="/no/existe-prueba.jar")
class CheckpointPr43SecondReviewTests(BaseCase):
    """Correcciones de la segunda revisión del PR #43 (ACT-307B)."""

    SPEC = {"name": "Registrar préstamo", "system_name": "Biblioteca", "primary_actors": ["Bibliotecario"],
            "secondary_actors": [], "preconditions": "El bibliotecario inició sesión.",
            "main_flow": ["El Bibliotecario captura la matrícula.", "El sistema registra el préstamo."],
            "alternate_flows": [], "postconditions": "El préstamo queda registrado.", "relations": [], "attempt_id": ""}

    def save(self, module, key, payload=None, revision=0, pause=False):
        return self.post(SAVE, {"module": module, "key": str(key), "revision": revision,
                                "payload": payload or {}, "pause": pause})

    def save_use_case(self, **extra):
        self.finished_attempt()
        return self.post("/modelado/api/guardar/", {**self.SPEC, **extra})

    def test_saving_a_new_use_case_consumes_its_draft(self):  # Hallazgo 1
        key = f"nuevo:{uuid.uuid4()}"
        other = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", key, payload={"name": "Borrador"})
        self.save("modeling", other, payload={"name": "Otro"})
        r = self.save_use_case(draft_key=key)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(PracticeCheckpoint.objects.values_list("key", flat=True)), [other])
        self.assertNotContains(self.client.get("/"), "Caso de uso · Borrador")

    def test_invalid_draft_key_does_not_break_the_save(self):  # Hallazgo 1
        for bad in ["nuevo:no-es-uuid", str(uuid.uuid4()), 7]:
            self.assertEqual(self.save_use_case(draft_key=bad).status_code, 200)

    def test_plain_new_editor_ignores_lesson_drafts(self):  # Hallazgo 2
        self.finished_attempt()
        lesson_draft, plain = f"nuevo:{uuid.uuid4()}", f"nuevo:{uuid.uuid4()}"
        self.save("modeling", lesson_draft, payload={"lesson_id": str(uuid.uuid4())})
        self.assertContains(self.client.get("/modelado/nuevo/"), 'data-draft-key=""')
        self.save("modeling", plain, payload={"name": "Libre"})
        self.save("modeling", lesson_draft, payload={"lesson_id": str(uuid.uuid4())}, revision=1)  # Más reciente.
        self.assertContains(self.client.get("/modelado/nuevo/"), f'data-draft-key="{plain}"')

    def test_disabled_module_hides_and_rejects_checkpoints(self):  # Hallazgo 6
        attempt = self.new_attempt()
        self.save("interview", attempt.id)
        key = f"nuevo:{uuid.uuid4()}"
        self.save("modeling", key, payload={"name": "Oculto"})
        with override_settings(INGENIALAB_MODULES=["interviews", "classification", "progress"]):
            index, drafts = checkpoints.for_dashboard(self.user)
            self.assertEqual((list(index), drafts), ([("interview", str(attempt.id))], []))
            self.assertEqual(self.save("modeling", f"nuevo:{uuid.uuid4()}").status_code, 404)
            self.assertEqual(self.client.get(f"{SAVE}modeling/{key}/").status_code, 404)

    def test_reset_and_discard_interview_clear_its_checkpoint(self):  # Hallazgos 7 y 8
        from apps.interviews.services import discard_interview, reset_interview
        attempt = self.new_attempt()
        self.save("interview", attempt.id, pause=True)
        reset_interview(attempt)
        self.assertFalse(PracticeCheckpoint.objects.exists())
        self.save("interview", attempt.id)
        discard_interview(attempt)
        self.assertFalse(PracticeCheckpoint.objects.exists())

    def test_deleting_a_use_case_clears_its_checkpoint(self):  # Hallazgo 8
        self.assertEqual(self.save_use_case().status_code, 200)
        from apps.modeling.models import UseCaseSpecification
        uc = UseCaseSpecification.objects.get(user=self.user)
        self.save("modeling", uc.id, payload={"name": "Cambiado"})
        self.client.post(f"/modelado/{uc.id}/eliminar/")
        self.assertFalse(UseCaseSpecification.objects.exists())
        self.assertFalse(PracticeCheckpoint.objects.exists())
