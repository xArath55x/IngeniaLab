"""Importa un banco de respuestas exportado con export_answer_bank (ACT-326).

    python manage.py seed_ingenialab                 # antes: crea las versiones de escenario
    python manage.py import_answer_bank banco.json --dry-run
    python manage.py import_answer_bank banco.json

Identifica cada variante por escenario, versión, ronda, calidad y hash de la pregunta, nunca por IDs.
Descarta las obsoletas y las que no pasan la validación vigente, no duplica las que ya existen y todo
ocurre en una transacción: si falta una versión de escenario, no se importa nada.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.interviews.answer_bank import BankFileError, import_bank


class Command(BaseCommand):
    help = "Importa a esta base un banco de respuestas exportado con export_answer_bank."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Archivo JSON exportado")
        parser.add_argument("--dry-run", action="store_true", help="Informa qué se importaría sin guardar nada")

    def handle(self, *args, file, dry_run, **opts):
        path = Path(file)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CommandError(f"No existe el archivo {path}.")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"{path} no es un JSON válido: {exc}")
        except OSError as exc:  # Carpeta, sin permisos, etc.
            raise CommandError(f"No se pudo leer {path}: {exc.strerror or exc}")
        try:
            reports = import_bank(data, dry_run=dry_run)
        except BankFileError as exc:
            raise CommandError(f"{exc} No se importó nada.")
        for report in reports:
            self.stdout.write(report.line())
        total = sum(r.counts["imported"] for r in reports)
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Simulación: se importarían {total} variantes. No se guardó nada."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Banco importado: {total} variantes nuevas."))
