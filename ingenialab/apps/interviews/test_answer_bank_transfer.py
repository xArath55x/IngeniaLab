"""Exportación e importación del banco de respuestas por escenario (ACT-326; SDS v3.0 §7.3)."""
import copy
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import CommandError, call_command

from apps.interviews import answer_bank, services
from apps.interviews.models import AnswerVariant, InterviewQuestion, ScenarioVersion
from apps.progress.tests import BaseCase


class BankCase(BaseCase):
    def setUp(self):
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "banco.json"
        rounds = services.rounds(self.version)
        self.high = self.version.questions.get(round_number=rounds[0], quality=InterviewQuestion.HIGH)
        self.low = self.version.questions.get(round_number=rounds[1], quality=InterviewQuestion.LOW)

    def variant(self, question, intro, **extra):
        segments = [{"text": intro, "req": None}] + [s for s in question.answer_segments if s.get("req")]
        return AnswerVariant.objects.create(version=self.version, round_number=question.round_number,
                                            quality=question.quality, question_hash=question.content_hash,
                                            segments=segments, model="qwen2.5:7b", **extra)

    def export(self, **opts):
        call_command("export_answer_bank", output=str(self.path), stdout=StringIO(), **opts)
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def import_(self, **opts):
        out = StringIO()
        call_command("import_answer_bank", str(self.path), stdout=out, **opts)
        return out.getvalue()

    def texts(self, **filters):
        return sorted(v.text for v in AnswerVariant.objects.filter(version=self.version, **filters))


class AnswerBankTransferTests(BankCase):

    def test_export_identifies_variants_without_database_ids(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        self.variant(self.low, "Pues no sé bien qué decirle.", is_active=False)
        data = self.export(scenario=["ESC-BIBLIOTECA-01"])
        self.assertEqual((data["format"], data["format_version"]), ("ingenialab-answer-bank", 1))
        [scenario] = data["scenarios"]
        self.assertEqual((scenario["scenario"], scenario["version"]), ("ESC-BIBLIOTECA-01", self.version.version_number))
        self.assertEqual(len(scenario["variants"]), 2)
        first = scenario["variants"][0]
        self.assertEqual(set(first), {"round_number", "quality", "question_hash", "segments", "model", "is_active"})
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.version.id), raw)
        self.assertNotIn(str(self.high.id), raw)
        self.assertIn("cómo trabajamos", raw)  # UTF-8 legible, sin escapes

    def test_export_active_only_and_all_scenarios(self):
        self.variant(self.high, "Activa.")
        self.variant(self.low, "Inactiva.", is_active=False)
        data = self.export(active_only=True)
        codes = [s["scenario"] for s in data["scenarios"]]
        self.assertEqual(codes, sorted(ScenarioVersion.objects.filter(is_active=True).values_list("scenario_code", flat=True)))
        biblioteca = next(s for s in data["scenarios"] if s["scenario"] == "ESC-BIBLIOTECA-01")
        self.assertEqual([v["segments"][0]["text"] for v in biblioteca["variants"]], ["Activa."])

    def test_export_unknown_scenario_fails(self):
        with self.assertRaisesMessage(CommandError, "ESC-NO-EXISTE"):
            self.export(scenario=["ESC-NO-EXISTE"])
        self.assertFalse(self.path.exists())

    def test_roundtrip_into_reseeded_database(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        self.variant(self.low, "Pues no sé bien qué decirle.", is_active=False)
        self.export(scenario=["ESC-BIBLIOTECA-01"])
        before = self.texts()
        AnswerVariant.objects.all().delete()
        call_command("seed_ingenialab", stdout=StringIO())  # otras preguntas, otros IDs
        recreated = self.version.questions.get(round_number=self.high.round_number, quality=InterviewQuestion.HIGH)
        self.assertNotEqual(recreated.id, self.high.id)
        out = self.import_()
        self.assertIn("2 importadas (1 inactivas)", out)
        self.assertEqual(self.texts(), before)
        self.assertEqual(self.texts(is_active=False), ["Pues no sé bien qué decirle."])
        served = services.bank_variant(self.new_attempt(), recreated)
        self.assertTrue(served.text.startswith("Mire, le explico"))
        self.assertEqual(served.model, "qwen2.5:7b")

    def test_import_is_idempotent(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        self.export(scenario=["ESC-BIBLIOTECA-01"])
        out = self.import_()
        self.assertIn("0 importadas", out)
        self.assertIn("1 ya existían", out)
        self.assertEqual(AnswerVariant.objects.count(), 1)

    def test_import_propagates_deactivation_but_never_reactivates(self):
        kept = self.variant(self.high, "La revisó el equipo.")
        off = self.variant(self.low, "Desactivada aquí.", is_active=False)
        data = self.export(scenario=["ESC-BIBLIOTECA-01"])
        for item in data["scenarios"][0]["variants"]:
            item["is_active"] = not item["is_active"]
        self.write(data)
        out = self.import_()
        self.assertIn("1 desactivadas", out)
        kept.refresh_from_db(); off.refresh_from_db()
        self.assertFalse(kept.is_active)
        self.assertFalse(off.is_active)

    def test_obsolete_invalid_and_malformed_variants_are_discarded(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        data = self.export(scenario=["ESC-BIBLIOTECA-01"])
        AnswerVariant.objects.all().delete()
        good = data["scenarios"][0]["variants"][0]
        obsolete = dict(copy.deepcopy(good), question_hash="0" * 64)
        # Revela un dato del escenario en una pregunta de calidad baja: no pasa la validación vigente.
        invalid = {"round_number": self.low.round_number, "quality": "low", "question_hash": self.low.content_hash,
                   "segments": [{"text": self.version.summary, "req": None}], "model": "x", "is_active": True}
        malformed = [{"round_number": "1", "quality": "high", "question_hash": "a", "segments": []},
                     dict(copy.deepcopy(good), quality="altísima"), dict(copy.deepcopy(good), segments=[{"text": " "}])]
        data["scenarios"][0]["variants"] = [good, obsolete, invalid, *malformed]
        self.write(data)
        out = self.import_()
        self.assertIn("1 importadas", out)
        self.assertIn("1 obsoletas, 1 no pasan la validación, 3 mal formadas", out)
        self.assertEqual(AnswerVariant.objects.count(), 1)

    def test_missing_scenario_version_aborts_without_changes(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        data = self.export()
        AnswerVariant.objects.all().delete()
        data["scenarios"].append({"scenario": "ESC-BIBLIOTECA-01", "version": "9.9", "variants": []})
        self.write(data)
        with self.assertRaisesMessage(CommandError, "No existe ESC-BIBLIOTECA-01 v9.9"):
            self.import_()
        self.assertEqual(AnswerVariant.objects.count(), 0)

    def test_dry_run_reports_without_saving(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        self.export(scenario=["ESC-BIBLIOTECA-01"])
        AnswerVariant.objects.all().delete()
        out = self.import_(dry_run=True)
        self.assertIn("1 importadas", out)
        self.assertIn("Simulación: se importarían 1 variantes", out)
        self.assertEqual(AnswerVariant.objects.count(), 0)

    def test_rejects_files_that_are_not_a_bank(self):
        cases = [("no es json", "no es un JSON válido"), ({"format": "otro"}, "no es un banco"),
                 ({"format": "ingenialab-answer-bank", "format_version": 2, "scenarios": []}, "no compatible"),
                 ({"format": "ingenialab-answer-bank", "format_version": 1, "scenarios": [{"scenario": "X"}]},
                  "necesita")]
        for content, message in cases:
            with self.subTest(message=message):
                self.path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
                with self.assertRaisesMessage(CommandError, message):
                    self.import_()
        with self.assertRaisesMessage(CommandError, "No existe el archivo"):
            call_command("import_answer_bank", str(self.path) + ".x", stdout=StringIO())

    def test_service_roundtrip_without_files(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        data = answer_bank.export_bank(["ESC-BIBLIOTECA-01"])
        AnswerVariant.objects.all().delete()
        [report] = answer_bank.import_bank(json.loads(json.dumps(data)))
        self.assertEqual(report.counts["imported"], 1)


class AnswerBankReviewFixesTests(BankCase):
    """Correcciones de la revisión del PR #47 (ACT-326)."""

    def exported_good(self):
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        data = self.export(scenario=["ESC-BIBLIOTECA-01"])
        AnswerVariant.objects.all().delete()
        return data, data["scenarios"][0]["variants"][0]

    def import_items(self, data, items):
        data["scenarios"][0]["variants"] = items
        self.write(data)
        return self.import_()

    def test_statements_must_match_the_catalog(self):  # Hallazgo 1
        data, good = self.exported_good()
        edited = copy.deepcopy(good)
        req = next(s for s in edited["segments"] if s.get("req"))
        req["text"] = "El sistema debe enviar SMS."
        invented = copy.deepcopy(good)
        invented["segments"].insert(1, {"text": "El sistema debe enviar SMS.", "req": "RF-X"})
        stray = {"round_number": self.low.round_number, "quality": "low", "question_hash": self.low.content_hash,
                 "segments": [{"text": "Pues no sé.", "req": None}, {"text": "Inventado.", "req": "RF-X"}]}
        out = self.import_items(data, [edited, invented, stray])
        self.assertIn("0 importadas", out)
        self.assertIn("3 no pasan la validación", out)

    def test_stores_the_validated_segments(self):  # Hallazgo 1
        data, good = self.exported_good()
        good["segments"][0]["text"] = "Mire,   le explico   cómo trabajamos hoy."
        self.import_items(data, [good])
        [variant] = AnswerVariant.objects.all()
        self.assertEqual(variant.segments[0]["text"], "Mire, le explico cómo trabajamos hoy.")

    def test_inactive_variants_are_validated_too(self):  # Hallazgo 2
        data, _ = self.exported_good()
        leak = {"round_number": self.low.round_number, "quality": "low", "question_hash": self.low.content_hash,
                "segments": [{"text": self.version.summary, "req": None}], "is_active": False}
        out = self.import_items(data, [leak])
        self.assertIn("1 no pasan la validación", out)
        self.assertFalse(AnswerVariant.objects.exists())

    def test_non_boolean_is_active_bool_round_and_extra_keys_are_malformed(self):  # Hallazgos 3 y 4
        data, good = self.exported_good()
        bad = [dict(copy.deepcopy(good), is_active=value) for value in (0, "false", None)]
        bad.append(dict(copy.deepcopy(good), round_number=True))
        extra = copy.deepcopy(good)
        extra["segments"][0]["html"] = "<b>x</b>"
        out = self.import_items(data, [*bad, extra])
        self.assertIn("5 mal formadas", out)
        self.assertFalse(AnswerVariant.objects.exists())

    def test_whitespace_variants_are_not_duplicated(self):  # Hallazgo 5
        self.variant(self.high, "Mire, le explico cómo trabajamos hoy.")
        data = self.export(scenario=["ESC-BIBLIOTECA-01"])
        data["scenarios"][0]["variants"][0]["segments"][0]["text"] = "Mire,  le explico cómo trabajamos hoy. "
        self.write(data)
        self.assertIn("1 ya existían", self.import_())
        self.assertEqual(AnswerVariant.objects.count(), 1)

    def test_unreadable_path_is_a_command_error(self):  # Hallazgo 6
        with self.assertRaisesMessage(CommandError, "No se pudo leer"):
            call_command("import_answer_bank", self.tmp.name, stdout=StringIO())

    def test_requirements_are_queried_once_per_question(self):  # Hallazgo 7
        data, good = self.exported_good()
        items = []
        for i in range(5):
            item = copy.deepcopy(good)
            item["segments"][0]["text"] = f"Mire, le explico cómo trabajamos hoy, versión {i}."
            items.append(item)
        data["scenarios"][0]["variants"] = items
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            [report] = answer_bank.import_bank(data)
        self.assertEqual(report.counts["imported"], 5)
        table = self.version.requirements.model._meta.db_table
        self.assertEqual(sum(q["sql"].startswith("SELECT") and f'FROM "{table}"' in q["sql"]
                             for q in ctx.captured_queries), 1)

    def test_export_unknown_scenario_is_not_a_file_error(self):  # Hallazgo 9
        with self.assertRaises(answer_bank.UnknownScenarioError):
            answer_bank.export_bank(["ESC-NO-EXISTE"])
        self.assertFalse(issubclass(answer_bank.UnknownScenarioError, answer_bank.BankFileError))
