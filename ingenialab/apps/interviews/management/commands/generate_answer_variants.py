"""Llena el banco de respuestas del cliente virtual con variantes redactadas por el LLM.

Se ejecuta antes de las prácticas (puede tardar varios minutos con un modelo local). Completa hasta
--per-question variantes activas por pregunta, así que puede interrumpirse y reanudarse. Las variantes
pasan la misma validación que la respuesta libre; las inválidas se descartan.

    INGENIALAB_AI_ENDPOINT=http://127.0.0.1:11434/v1/chat/completions INGENIALAB_AI_MODEL=qwen2.5:7b \\
        python manage.py generate_answer_variants --scenario ESC-BIBLIOTECA-01
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.interviews.models import AnswerVariant, ScenarioVersion
from integrations.ai import dialogue


class Command(BaseCommand):
    help = "Genera con el LLM variantes de la respuesta del cliente para cada pregunta de los escenarios activos."

    def add_arguments(self, parser):
        parser.add_argument("--scenario", action="append", help="Código del escenario (repetible); por defecto, todos los activos")
        parser.add_argument("--per-question", type=int, default=5, help="Variantes activas por pregunta (default 5)")
        parser.add_argument("--timeout", type=float, default=90, help="Segundos máximos por llamada al LLM")

    def handle(self, *args, **opts):
        per_question = opts["per_question"]
        if per_question < 1:
            raise CommandError("--per-question debe ser al menos 1.")
        versions = ScenarioVersion.objects.filter(is_active=True)
        if opts["scenario"]:
            versions = versions.filter(scenario_code__in=opts["scenario"])
        if not versions.exists():
            raise CommandError("No hay escenarios activos con esos códigos.")
        model = settings.INGENIALAB_AI_MODEL
        totals = {"created": 0, "rejected": 0, "errors": 0}
        start = time.monotonic()
        for version in versions:
            self.stdout.write(self.style.MIGRATE_HEADING(f"{version} · {version.title}"))
            for question in version.questions.order_by("round_number", "order"):
                created, rejected, errors = self._fill(question, per_question, opts["timeout"], model)
                for key, value in zip(totals, (created, rejected, errors)):
                    totals[key] += value
                have = AnswerVariant.for_question(question).filter(is_active=True).count()
                self.stdout.write(f"  ronda {question.round_number} · {question.get_quality_display():<9} "
                                  f"{have}/{per_question} variantes (+{created}, rechazadas {rejected}, errores {errors})")
        minutes = (time.monotonic() - start) / 60
        self.stdout.write(self.style.SUCCESS(
            f"Listo en {minutes:.1f} min: {totals['created']} variantes nuevas, {totals['rejected']} rechazadas "
            f"por validación, {totals['errors']} errores del proveedor. Revísalas en el admin (Answer variants)."))

    def _fill(self, question, per_question, timeout, model):
        """Genera hasta completar las variantes activas; como máximo el doble de intentos."""
        created = rejected = errors = 0
        existing = AnswerVariant.for_question(question)
        texts = {" ".join(s["text"] for s in segments) for segments in existing.values_list("segments", flat=True)}
        missing = per_question - existing.filter(is_active=True).count()
        for _ in range(max(0, missing) * 2):
            if created >= missing:
                break
            try:
                segments = dialogue.generate_variant(question, timeout)
            except ValueError as exc:
                if "Configura" in str(exc):
                    raise CommandError(str(exc))
                rejected += 1
                continue
            except Exception:  # Red, tiempo agotado o JSON del proveedor ilegible.
                errors += 1
                continue
            text = " ".join(s["text"] for s in segments)
            if text in texts:
                rejected += 1
                continue
            texts.add(text)
            AnswerVariant.objects.create(
                version=question.version, round_number=question.round_number, quality=question.quality,
                question_hash=question.content_hash, segments=segments, model=model,
            )
            created += 1
        return created, rejected, errors
