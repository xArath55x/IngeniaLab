"""Exportación e importación del banco de respuestas por escenario (ACT-326; SDS v3.0 §7.3).

Permite generar el banco en un equipo con LLM y cargarlo en producción, que no ejecuta ningún modelo.
El archivo identifica cada variante por código y versión de escenario, ronda, calidad y hash de la
pregunta; nunca por IDs de la base, que cambian entre equipos y al volver a sembrar los escenarios.

Reglas de importación:
1. La versión del escenario debe existir (correr antes seed_ingenialab); si falta alguna, no se importa nada.
2. Una variante cuyo question_hash ya no coincide con la pregunta del catálogo se descarta (obsoleta).
3. Toda variante nueva, activa o inactiva, pasa la validación vigente (dialogue.revalidate_variant); las que no,
   se descartan. Se guardan los segmentos que devuelve la validación, nunca los del archivo, y los enunciados
   evaluables (`req`) deben ser idénticos a los del catálogo: así una inactiva reactivada en el admin es segura.
4. Una variante con el mismo texto (sin contar espacios) que otra existente no se duplica, así que importar dos
   veces es seguro. Si el archivo la trae desactivada y aquí está activa, se desactiva; nunca se reactiva.
5. Todo ocurre en una transacción; con dry_run se informa el resultado sin guardar nada.
"""
from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from integrations.ai import dialogue

from .models import AnswerVariant, InterviewQuestion, ScenarioVersion

FORMAT = "ingenialab-answer-bank"
FORMAT_VERSION = 1
QUALITIES = {q for q, _ in InterviewQuestion.QUALITIES}


class BankFileError(ValueError):
    """El archivo no tiene el formato esperado o falta una versión de escenario; no se importó nada."""


class UnknownScenarioError(ValueError):
    """Se pidió exportar un escenario sin versión activa."""


def _versions(codes=None):
    versions = ScenarioVersion.objects.filter(is_active=True)
    if codes:
        versions = versions.filter(scenario_code__in=codes)
        missing = set(codes) - set(versions.values_list("scenario_code", flat=True))
        if missing:
            raise UnknownScenarioError(f"No hay una versión activa de: {', '.join(sorted(missing))}.")
    return versions.order_by("scenario_code")


def export_bank(codes=None, active_only=False):
    """Diccionario serializable con las variantes de las versiones activas de los escenarios indicados."""
    scenarios = []
    for version in _versions(codes):
        variants = version.answer_variants.order_by("round_number", "quality", "created_at", "id")
        if active_only:
            variants = variants.filter(is_active=True)
        scenarios.append({
            "scenario": version.scenario_code,
            "version": version.version_number,
            "title": version.title,
            "variants": [{"round_number": v.round_number, "quality": v.quality, "question_hash": v.question_hash,
                          "segments": v.segments, "model": v.model, "is_active": v.is_active} for v in variants],
        })
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "exported_at": timezone.localtime().isoformat(timespec="seconds"), "scenarios": scenarios}


def _dedup_text(text):
    """Texto de una variante para no duplicarla: los espacios repetidos no la hacen distinta."""
    return " ".join(text.split())


def _check_segments(segments):
    if not isinstance(segments, list) or not segments:
        return False
    for s in segments:
        if not isinstance(s, dict) or set(s) - {"text", "req"} or not isinstance(s.get("text"), str) \
                or not s["text"].strip():
            return False
        if s.get("req") is not None and not isinstance(s["req"], str):
            return False
    return True


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass
class _Target:
    """Pregunta del catálogo con lo que se calcula una sola vez por pregunta, no por variante."""
    question: InterviewQuestion
    content_hash: str
    statements: list
    facts: list = None


def _validated_segments(item, target):
    """Segmentos limpios de la variante, o ValueError si no pasa la validación vigente."""
    statements = [{"text": s["text"], "req": s["req"]} for s in item["segments"] if s.get("req")]
    if statements != target.statements:
        raise ValueError("Los enunciados evaluables no coinciden con el catálogo")
    if target.facts is None:
        target.facts = dialogue.scenario_facts(target.question)
    return dialogue.revalidate_variant(item["segments"], target.question, facts=target.facts)


def _check_file(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BankFileError("El archivo no es un banco de respuestas de IngeniaLab.")
    if data.get("format_version") != FORMAT_VERSION:
        raise BankFileError(f"Versión de formato no compatible: {data.get('format_version')!r} (se esperaba {FORMAT_VERSION}).")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        raise BankFileError("Falta la lista «scenarios».")
    for entry in scenarios:
        if not isinstance(entry, dict) or not isinstance(entry.get("scenario"), str) \
                or not isinstance(entry.get("version"), str) or not isinstance(entry.get("variants"), list):
            raise BankFileError("Cada escenario necesita «scenario», «version» y «variants».")
    return scenarios


@dataclass
class ScenarioReport:
    scenario: str
    version: str
    counts: Counter = field(default_factory=Counter)

    def line(self):
        c = self.counts
        return (f"{self.scenario} v{self.version}: {c['imported']} importadas ({c['imported_inactive']} inactivas), "
                f"{c['duplicate']} ya existían, {c['deactivated']} desactivadas, {c['obsolete']} obsoletas, "
                f"{c['invalid']} no pasan la validación, {c['malformed']} mal formadas")


def import_bank(data, dry_run=False):
    """Carga el banco en esta base. Devuelve un ScenarioReport por escenario; lanza BankFileError sin cambios."""
    scenarios = _check_file(data)
    targets = []
    for entry in scenarios:
        try:
            version = ScenarioVersion.objects.get(scenario_code=entry["scenario"], version_number=entry["version"])
        except ScenarioVersion.DoesNotExist:
            raise BankFileError(f"No existe {entry['scenario']} v{entry['version']} en esta base. "
                                "Corre primero manage.py seed_ingenialab.")
        targets.append((version, entry))

    reports = []
    with transaction.atomic():
        for version, entry in targets:
            report = ScenarioReport(version.scenario_code, version.version_number)
            questions = {(q.round_number, q.quality): _Target(q, q.content_hash,
                                                              [{"text": s["text"], "req": s["req"]}
                                                               for s in q.answer_segments if s.get("req")])
                         for q in version.questions.all()}
            existing = {}
            for v in version.answer_variants.all():
                existing.setdefault((v.round_number, v.quality, v.question_hash, _dedup_text(v.text)), v)
            for item in entry["variants"]:
                _import_variant(version, item, questions, existing, report.counts)
            reports.append(report)
        if dry_run:
            transaction.set_rollback(True)
    return reports


def _import_variant(version, item, questions, existing, counts):
    if not isinstance(item, dict) or item.get("quality") not in QUALITIES \
            or not _is_int(item.get("round_number")) or not isinstance(item.get("question_hash"), str) \
            or not isinstance(item.get("is_active", True), bool) or not _check_segments(item.get("segments")):
        counts["malformed"] += 1
        return
    target = questions.get((item["round_number"], item["quality"]))
    if target is None or target.content_hash != item["question_hash"]:
        counts["obsolete"] += 1
        return
    active = item.get("is_active", True)
    key = (item["round_number"], item["quality"], item["question_hash"],
           _dedup_text(" ".join(s["text"] for s in item["segments"])))
    current = existing.get(key)
    if current is not None:
        if current.is_active and not active:
            current.is_active = False
            current.save(update_fields=["is_active"])
            counts["deactivated"] += 1
        else:
            counts["duplicate"] += 1
        return
    try:
        segments = _validated_segments(item, target)
    except ValueError:
        counts["invalid"] += 1
        return
    existing[key] = AnswerVariant.objects.create(
        version=version, round_number=item["round_number"], quality=item["quality"],
        question_hash=item["question_hash"], segments=segments,
        model=str(item.get("model") or "")[:100], is_active=active)
    counts["imported"] += 1
    if not active:
        counts["imported_inactive"] += 1
