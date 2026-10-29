"""Banco de respuestas del cliente redactadas por el LLM antes de la práctica (CU-01)."""
from io import StringIO
import secrets
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.interviews import services
from apps.interviews.models import AnswerVariant, InterviewQuestion
from apps.progress.tests import BaseCase
from integrations.ai import dialogue

LLM = override_settings(INGENIALAB_AI_MODE="chat_completions", INGENIALAB_AI_ENDPOINT="http://127.0.0.1:9999/v1/chat/completions",
                        INGENIALAB_AI_MODEL="prueba", INGENIALAB_AI_FREE_ANSWERS=True, INGENIALAB_AI_FREE_TIMEOUT=2)


def fake_llm(payload, endpoint, key, model, timeout, system=None, temperature=None):
    if system == dialogue.SYSTEM_JUDGE:
        return {"answers_question": True, "reason": "Contesta."}
    return {"intro": f"Le cuento algo distinto {secrets.token_hex(4)}.", "closing": ""}


def generation_calls(llm):
    return [c for c in llm.call_args_list if c.args[5] == dialogue.SYSTEM_FREE]


@LLM
class AnswerBankTests(BaseCase):
    def high(self, round_index=0):
        number = services.rounds(self.version)[round_index]
        return self.version.questions.get(round_number=number, quality=InterviewQuestion.HIGH)

    def variant(self, question, intro, **extra):
        segments = [{"text": intro, "req": None}] + [s for s in question.answer_segments if s.get("req")]
        return AnswerVariant.objects.create(version=self.version, round_number=question.round_number,
                                            quality=question.quality, question_hash=question.content_hash,
                                            segments=segments, **extra)

    def test_bank_answer_is_served_without_calling_llm(self):
        question = self.high()
        self.variant(question, "Mire, le explico cómo trabajamos hoy.")
        attempt = self.new_attempt()
        with mock.patch("integrations.ai.dialogue._request") as llm:
            r = self.ask(attempt, question).json()
        llm.assert_not_called()
        self.assertEqual(r["entry"]["source"], "ai_bank")
        self.assertEqual(r["entry"]["segments"][0]["text"], "Mire, le explico cómo trabajamos hoy.")
        self.assertTrue(any(s["req_id"] for s in r["entry"]["segments"]))

    def test_choice_is_stable_per_attempt_and_varies_between_attempts(self):
        question = self.high()
        for _ in range(5):
            self.variant(question, f"Variante {secrets.token_hex(4)}.")
        attempt = self.new_attempt()
        self.assertEqual(services.bank_variant(attempt, question), services.bank_variant(attempt, question))
        chosen = {services.bank_variant(self.new_attempt(), question).id for _ in range(10)}
        self.assertGreater(len(chosen), 1)

    def test_inactive_and_outdated_variants_are_ignored(self):
        question = self.high()
        self.variant(question, "Desactivada por el docente.", is_active=False)
        stale = self.variant(question, "De un contenido anterior.")
        AnswerVariant.objects.filter(id=stale.id).update(question_hash="0" * 64)
        attempt = self.new_attempt()
        with mock.patch("integrations.ai.dialogue._request", side_effect=OSError("sin proveedor")):
            r = self.ask(attempt, question).json()
        self.assertEqual(r["entry"]["source"], "catalog")

    def test_setting_can_disable_bank(self):
        question = self.high()
        self.variant(question, "No debería usarse.")
        attempt = self.new_attempt()
        with self.settings(INGENIALAB_AI_ANSWER_BANK=False, INGENIALAB_AI_MODE="catalog"):
            r = self.ask(attempt, question).json()
        self.assertEqual(r["entry"]["source"], "catalog")

    def test_bank_survives_reseeding_scenario_without_practices(self):
        question = self.high()
        self.variant(question, "Sigo aquí después del seed.")
        call_command("seed_ingenialab", stdout=StringIO())
        recreated = self.high()
        self.assertNotEqual(recreated.id, question.id)
        self.assertEqual(services.bank_variant(self.new_attempt(), recreated).text.split(".")[0], "Sigo aquí después del seed")

    def test_command_fills_bank_and_resumes(self):
        with mock.patch("integrations.ai.dialogue._request", side_effect=fake_llm) as llm:
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=2, stdout=StringIO())
            questions = self.version.questions.count()
            self.assertEqual(len(generation_calls(llm)), questions * 2)
            # Solo las respuestas sin enunciados evaluables pasan por la revisión de relevancia.
            vague = sum(not any(s.get("req") for s in q.answer_segments) for q in self.version.questions.all())
            self.assertEqual(llm.call_count, questions * 2 + vague * 2)
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=2, stdout=StringIO())
            self.assertEqual(llm.call_count, questions * 2 + vague * 2)
        self.assertEqual(AnswerVariant.objects.filter(version=self.version, is_active=True).count(), questions * 2)
        self.assertEqual(generation_calls(llm)[0].args[-1], 0.9)

    def test_command_discards_answers_that_do_not_answer_the_question(self):
        verdicts = iter([False] + [True] * 500)

        def llm(payload, *args):
            if args[4] == dialogue.SYSTEM_JUDGE:
                return {"answers_question": next(verdicts), "reason": "Cambia de tema."}
            return fake_llm(payload, *args)
        out = StringIO()
        with mock.patch("integrations.ai.dialogue._request", side_effect=llm):
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1, stdout=out)
        self.assertIn("(1 por no contestar la pregunta)", out.getvalue())
        self.assertEqual(AnswerVariant.objects.filter(version=self.version).count(), self.version.questions.count())

    def test_quality_option_limits_questions(self):
        with mock.patch("integrations.ai.dialogue._request", side_effect=fake_llm):
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1,
                         quality=["high", "medium"], stdout=StringIO())
        qualities = set(AnswerVariant.objects.filter(version=self.version).values_list("quality", flat=True))
        self.assertEqual(qualities, {"high", "medium"})

    def test_answers_with_statements_skip_relevance_review(self):
        with mock.patch("integrations.ai.dialogue._request", side_effect=fake_llm) as llm:
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1,
                         quality=["high"], stdout=StringIO())
        self.assertEqual(len(generation_calls(llm)), llm.call_count)

    def test_no_judge_skips_relevance_review(self):
        with mock.patch("integrations.ai.dialogue._request", side_effect=fake_llm) as llm:
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1, no_judge=True,
                         stdout=StringIO())
        self.assertEqual(len(generation_calls(llm)), llm.call_count)

    def test_revalidate_keeps_variant_when_review_is_unavailable(self):
        question = self.high()
        kept = self.variant(question, "Mire, hoy todo es manual.")
        with mock.patch("integrations.ai.dialogue._request", side_effect=OSError("sin red")):
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1,
                         revalidate=True, stdout=StringIO())
        kept.refresh_from_db()
        self.assertTrue(kept.is_active)

    def test_revalidate_deactivates_variant_rejected_by_judge(self):
        low = self.version.questions.get(round_number=services.rounds(self.version)[0], quality=InterviewQuestion.LOW)
        rejected = self.variant(low, "Mire, hoy todo es manual.")
        verdicts = iter([False] + [True] * 500)

        def llm(payload, *args):
            if args[4] == dialogue.SYSTEM_JUDGE:
                return {"answers_question": next(verdicts), "reason": "Cambia de tema."}
            return fake_llm(payload, *args)
        out = StringIO()
        with mock.patch("integrations.ai.dialogue._request", side_effect=llm):
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1,
                         quality=["low"], revalidate=True, stdout=out)
        rejected.refresh_from_db()
        self.assertFalse(rejected.is_active)
        self.assertIn("1 variantes desactivadas", out.getvalue())
        # El rechazo de la revalidación no se cuenta entre las variantes nuevas rechazadas.
        self.assertIn("(0 por no contestar la pregunta)", out.getvalue())

    def test_command_discards_invalid_answers(self):
        generated = []

        def llm(payload, *args):
            if args[4] == dialogue.SYSTEM_FREE:
                generated.append(payload)
                if len(generated) == 1:  # la primera revela una cifra del escenario
                    return {"intro": "Hay alumnos con tres libros prestados a la vez.", "closing": ""}
            return fake_llm(payload, *args)
        with mock.patch("integrations.ai.dialogue._request", side_effect=llm):
            out = StringIO()
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1, stdout=out)
        self.assertIn("1 rechazadas", out.getvalue())

    def test_revalidate_deactivates_variants_that_no_longer_pass(self):
        low = self.version.questions.get(round_number=services.rounds(self.version)[0], quality=InterviewQuestion.LOW)
        bad = self.variant(low, self.version.summary)
        with mock.patch("integrations.ai.dialogue._request", side_effect=fake_llm):
            out = StringIO()
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1,
                         revalidate=True, stdout=out)
        bad.refresh_from_db()
        self.assertFalse(bad.is_active)
        self.assertIn("1 variantes desactivadas", out.getvalue())
        self.assertEqual(AnswerVariant.for_question(low).filter(is_active=True).count(), 1)

    def test_command_requires_provider(self):
        with self.settings(INGENIALAB_AI_ENDPOINT=""), self.assertRaisesMessage(CommandError, "INGENIALAB_AI_ENDPOINT"):
            call_command("generate_answer_variants", scenario=["ESC-BIBLIOTECA-01"], per_question=1, stdout=StringIO())

    def test_admin_lists_variants(self):
        self.variant(self.high(), "Visible en el admin.")
        User.objects.create_superuser("docente", password="ClaveSegura123")
        self.client.login(username="docente", password="ClaveSegura123")
        r = self.client.get("/admin/interviews/answervariant/")
        self.assertContains(r, "Visible en el admin.")
