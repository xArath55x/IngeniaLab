"""Respuesta libre del cliente virtual (CU-01, solicitud de la cliente).

El LLM redacta la respuesta a las preguntas del catálogo; los enunciados evaluables se conservan
textuales y ninguna otra oración puede contar requisitos del escenario.
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.interviews.models import InterviewQuestion
from apps.progress.tests import BaseCase

from . import dialogue

FREE = override_settings(
    INGENIALAB_AI_MODE="chat_completions", INGENIALAB_AI_ENDPOINT="http://127.0.0.1:9999/v1/chat/completions",
    INGENIALAB_AI_MODEL="modelo-prueba", INGENIALAB_AI_FREE_ANSWERS=True, INGENIALAB_AI_FREE_TIMEOUT=2,
)
B01 = "Queremos que el sistema registre cada préstamo con el alumno, el libro y la fecha de devolución."
B04 = "El sistema debe impedir el préstamo si el alumno ya tiene tres libros prestados."
CATALOG = [{"text": "Hoy llevamos los préstamos en libretas.", "req": None}, {"text": B01, "req": "B01"}]


def question(segments=CATALOG):
    version = SimpleNamespace(
        title="Biblioteca", summary="Préstamos de la biblioteca escolar.", client_name="Lic. Ana", client_role="Coordinadora",
        requirements=SimpleNamespace(all=lambda: [SimpleNamespace(statement_text=s) for s in (B01, B04)]),
    )
    return SimpleNamespace(text="¿Cuál es el problema principal?", topic="Objetivo", version=version,
                           answer_segments=deepcopy(segments))


OK = {"intro": "Mire, todo lo anotamos a mano y cada mes se nos pierden ejemplares.", "closing": ""}


@FREE
class FreeAnswerTests(SimpleTestCase):
    @patch("integrations.ai.dialogue._request")
    def test_conversation_wraps_statement_verbatim(self, request):
        request.return_value = {**OK, "closing": "Ojalá eso nos ayude a no perder más."}
        result = dialogue.answer(question())
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.segments, [
            {"text": OK["intro"], "req": None}, {"text": B01, "req": "B01"},
            {"text": "Ojalá eso nos ayude a no perder más.", "req": None},
        ])

    @patch("integrations.ai.dialogue._request")
    def test_invalid_answers_fall_back_to_catalog(self, request):
        cases = {
            "formato anterior": {"segments": deepcopy(CATALOG)},
            "sin intro": {"intro": "  ", "closing": ""},
            "claves extra": {**OK, "req": "B99"},
            "repite el enunciado": {"intro": B01, "closing": ""},
            "filtra otro requisito": {"intro": "Y no prestamos si el alumno ya tiene tres libros prestados.", "closing": ""},
            "revela una cifra con otras palabras": {"intro": "Hay alumnos que se llevan hasta tres libros a la vez.", "closing": ""},
            "otro idioma": {"intro": "Es特别地，我们希望每月都能收到报告。", "closing": ""},
            "cierre demasiado largo": {**OK, "closing": "x" * 401},
        }
        for name, response in cases.items():
            with self.subTest(name):
                request.return_value = response
                result = dialogue.answer(question())
                self.assertEqual((result.source, result.reason), ("catalog", "invalid_response"))
                self.assertEqual(result.segments, CATALOG)

    @patch("integrations.ai.dialogue._request")
    def test_vague_answer_has_no_statements(self, request):
        vague = [{"text": "Pues que funcione bien, supongo.", "req": None}]
        request.return_value = {"intro": "Que sea práctico para todos, a las dos de la tarde lo platicamos.", "closing": ""}
        result = dialogue.answer(question(vague))
        self.assertEqual(result.source, "ai")
        self.assertEqual([s["req"] for s in result.segments], [None])
        # Pregunta sin relación respondida recitando el escenario: se rechaza.
        request.return_value = {"intro": "En la biblioteca escolar llevamos los préstamos a mano, es tedioso.", "closing": ""}
        self.assertEqual(dialogue.answer(question(vague)).reason, "invalid_response")

    @patch("integrations.ai.dialogue._request")
    def test_payload_hides_statements_when_they_follow(self, request):
        request.return_value = OK
        dialogue.answer(question())
        payload, *_, system = request.call_args.args
        self.assertEqual(system, dialogue.SYSTEM_FREE)
        self.assertTrue(payload["needs_follow"])
        self.assertEqual(payload["current_situation"], "Hoy llevamos los préstamos en libretas.")
        self.assertEqual(payload["topic"], "Objetivo")
        # Un modelo pequeño repite los enunciados si los ve; solo la validación los usa.
        self.assertNotIn("préstamo con el alumno", str(payload))
        self.assertNotIn("scenario_facts", payload)
        self.assertIn("summary", payload)

    @patch("integrations.ai.dialogue._request")
    def test_payload_for_vague_answer_includes_facts(self, request):
        request.return_value = {"intro": "Pues que funcione bien.", "closing": ""}
        dialogue.answer(question([{"text": "Pues sí, supongo.", "req": None}]))
        payload = request.call_args.args[0]
        self.assertFalse(payload["needs_follow"])
        self.assertEqual(payload["reference_answer"], "Pues sí, supongo.")
        self.assertEqual(payload["scenario_facts"], [B01, B04])
        self.assertNotIn("summary", payload)

    @patch("integrations.ai.dialogue._request")
    def test_free_mode_has_its_own_timeout_limit(self, request):
        request.return_value = OK
        with self.settings(INGENIALAB_AI_FREE_TIMEOUT=30, INGENIALAB_AI_TIMEOUT=0):
            self.assertEqual(dialogue.answer(question()).source, "ai")
        with self.settings(INGENIALAB_AI_FREE_TIMEOUT=31):
            self.assertEqual(dialogue.answer(question()).reason, "configuration")
        with self.settings(INGENIALAB_AI_FREE_ANSWERS=False, INGENIALAB_AI_TIMEOUT=8):
            self.assertEqual(dialogue.answer(question()).reason, "configuration")


@FREE
class FreeAnswerInterviewTests(BaseCase):
    def test_interview_stores_free_answer_and_classification_uses_it(self):
        attempt = self.new_attempt()
        high = self.version.questions.filter(quality=InterviewQuestion.HIGH).first()
        required = [s for s in high.answer_segments if s.get("req")]
        llm = {"intro": "Le cuento con calma cómo trabajamos hoy en la biblioteca.", "closing": ""}
        with patch("integrations.ai.dialogue._request", return_value=llm):
            r = self.ask(attempt, high).json()
        self.assertEqual(r["entry"]["source"], "ai")
        self.assertEqual(r["entry"]["segments"][0]["text"], "Le cuento con calma cómo trabajamos hoy en la biblioteca.")
        entry = attempt.log_entries.get()
        self.assertEqual([s["text"] for s in entry.response_segments if s["req"]], [s["text"] for s in required])
        page = self.client.get(f"/elicitacion/intento/{attempt.id}/")
        self.assertContains(page, "Le cuento con calma")

    def test_browser_waits_longer_only_in_free_mode(self):
        attempt = self.new_attempt()
        with self.settings(INGENIALAB_AI_FREE_TIMEOUT=20):
            self.assertEqual(self.client.get(f"/elicitacion/intento/{attempt.id}/").context["ask_timeout_ms"], 25000)
        with self.settings(INGENIALAB_AI_FREE_ANSWERS=False):
            self.assertEqual(self.client.get(f"/elicitacion/intento/{attempt.id}/").context["ask_timeout_ms"], 10000)
