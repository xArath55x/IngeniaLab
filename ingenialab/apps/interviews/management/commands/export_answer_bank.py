"""Exporta el banco de respuestas a un archivo JSON, por código de escenario (ACT-326).

    python manage.py export_answer_bank --scenario ESC-BIBLIOTECA-01 --output banco.json
    python manage.py export_answer_bank --output banco_todos.json   # todos los escenarios activos

Incluye las variantes desactivadas (con is_active=false) para conservar la revisión del equipo;
usa --active-only para llevar solo las que se muestran. El archivo no contiene datos de alumnos.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.interviews.answer_bank import UnknownScenarioError, export_bank


class Command(BaseCommand):
    help = "Exporta las variantes del banco de respuestas de los escenarios activos a un archivo JSON."

    def add_arguments(self, parser):
        parser.add_argument("--scenario", action="append", help="Código del escenario (repetible); por defecto, todos los activos")
        parser.add_argument("--output", required=True, help="Archivo de salida (.json); «-» para la salida estándar")
        parser.add_argument("--active-only", action="store_true", help="Exporta solo las variantes activas")

    def handle(self, *args, **opts):
        try:
            data = export_bank(opts["scenario"], active_only=opts["active_only"])
        except UnknownScenarioError as exc:
            raise CommandError(str(exc))
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if opts["output"] == "-":
            self.stdout.write(text, ending="")
            return
        path = Path(opts["output"])
        if path.parent and not path.parent.exists():
            raise CommandError(f"No existe la carpeta {path.parent}.")
        path.write_text(text, encoding="utf-8")
        for scenario in data["scenarios"]:
            active = sum(1 for v in scenario["variants"] if v["is_active"])
            self.stdout.write(f"{scenario['scenario']} v{scenario['version']}: {len(scenario['variants'])} variantes "
                              f"({active} activas)")
        self.stdout.write(self.style.SUCCESS(f"Banco exportado en {path}."))
