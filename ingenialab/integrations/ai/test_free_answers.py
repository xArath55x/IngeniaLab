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
    return SimpleNamespace(text="¿Cuál es el problema principal?", version=version, answer_segments=deepcopy(segments))


@FREE
class FreeAnswerTests(SimpleTestCase):
    @patch("integrations.ai.dialogue._request")
    def test_new_conversation_keeps_statement_verbatim(self, request):
        request.return_value = {"segments": [
            {"text": "Mire, todo lo anotamos a mano y cada mes se nos pierden ejemplares.", "req": None},
            {"text": "Necesitamos registrar cada préstamo con alumno, libro y fecha.", "req": "B01"},
        ]}
        result = dialogue.answer(question())
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.segments[0]["text"], "Mire, todo lo anotamos a mano y cada mes se nos pierden ejemplares.")
        self.assertEqual(result.segments[1], {"text": B01, "req": "B01"})

    @patch("integrations.ai.dialogue._request")
    def test_invalid_answers_fall_back_to_catalog(self, request):
        cases = {
            "falta el enunciado": [{"text": "Se nos pierden libros.", "req": None}],
            "enunciado repetido": [{"text": B01, "req": "B01"}, {"text": B01, "req": "B01"}],
            "clave inventada": [{"text": B01, "req": "B01"}, {"text": "Otra cosa.", "req": "B99"}],
            "lo cuenta sin marcar": [{"text": B01, "req": None}, {"text": B01, "req": "B01"}],
            "filtra otro requisito": [{"text": B01, "req": "B01"},
                                      {"text": "Y no prestamos si el alumno ya tiene tres libros prestados.", "req": None}],
            "sin segmentos": [],
            "otro idioma": [{"text": "Es特别地，我们希望每月都能收到报告。", "req": None}, {"text": B01, "req": "B01"}],
        }
        for name, segments in cases.items():
            with self.subTest(name):
                request.return_value = {"segments": segments}
                result = dialogue.answer(question())
                self.assertEqual((result.source, result.reason), ("catalog", "invalid_response"))
                self.assertEqual(result.segments, CATALOG)

    @patch("integrations.ai.dialogue._request")
    def test_vague_answer_cannot_mark_requirements(self, request):
        vague = [{"text": "Pues que funcione bien, supongo.", "req": None}]
        request.return_value = {"segments": [{"text": "Algo general.", "req": None}, {"text": B01, "req": "B01"}]}
        self.assertEqual(dialogue.answer(question(vague)).reason, "invalid_response")
        request.return_value = {"segments": [{"text": "Que sea práctico para todos, nada más.", "req": None}]}
        self.assertEqual(dialogue.answer(question(vague)).source, "ai")

    @patch("integrations.ai.dialogue._request")
    def test_payload_and_prompt(self, request):
        request.return_value = {"segments": deepcopy(CATALOG)}
        dialogue.answer(question())
        payload, *_, system = request.call_args.args
        self.assertEqual(set(payload), {"scenario", "summary", "client", "question", "reference_answer",
                                        "required_statements", "scenario_facts"})
        self.assertEqual(payload["required_statements"], [{"req": "B01", "text": B01}])
        self.assertEqual(payload["scenario_facts"], [B01, B04])
        self.assertEqual(system, dialogue.SYSTEM_FREE)

    @patch("integrations.ai.dialogue._request")
    def test_free_mode_has_its_own_timeout_limit(self, request):
        request.return_value = {"segments": deepcopy(CATALOG)}
        with self.settings(INGENIALAB_AI_FREE_TIMEOUT=8, INGENIALAB_AI_TIMEOUT=0):
            self.assertEqual(dialogue.answer(question()).source, "ai")
        with self.settings(INGENIALAB_AI_FREE_TIMEOUT=9):
            self.assertEqual(dialogue.answer(question()).reason, "configuration")
        with self.settings(INGENIALAB_AI_FREE_ANSWERS=False, INGENIALAB_AI_TIMEOUT=8):
            self.assertEqual(dialogue.answer(question()).reason, "configuration")


@FREE
class FreeAnswerInterviewTests(BaseCase):
    def test_interview_stores_free_answer_and_classification_uses_it(self):
        attempt = self.new_attempt()
        high = self.version.questions.filter(quality=InterviewQuestion.HIGH).first()
        required = [s for s in high.answer_segments if s.get("req")]
        llm = {"segments": [{"text": "Le cuento con calma cómo trabajamos hoy en la biblioteca.", "req": None},
                            *({"text": "versión libre", "req": s["req"]} for s in required)]}
        with patch("integrations.ai.dialogue._request", return_value=llm):
            r = self.ask(attempt, high).json()
        self.assertEqual(r["entry"]["source"], "ai")
        self.assertEqual(r["entry"]["segments"][0]["text"], "Le cuento con calma cómo trabajamos hoy en la biblioteca.")
        entry = attempt.log_entries.get()
        self.assertEqual([s["text"] for s in entry.response_segments if s["req"]], [s["text"] for s in required])
        page = self.client.get(f"/elicitacion/intento/{attempt.id}/")
        self.assertContains(page, "Le cuento con calma")
