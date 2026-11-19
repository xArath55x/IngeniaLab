"""Borra los puntos de autoguardado sin cambios en N días (CU-10 RN-03). Pensado para cron diario."""
from django.core.management.base import BaseCommand, CommandError

from apps.progress.checkpoints import PURGE_DAYS, purge


class Command(BaseCommand):
    help = "Borra los autoguardados (PracticeCheckpoint) sin cambios en los últimos N días."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=PURGE_DAYS, help=f"Antigüedad mínima en días (default {PURGE_DAYS})")

    def handle(self, *args, days, **options):
        if days < 1:
            raise CommandError("--days debe ser 1 o mayor.")
        deleted = purge(days=days)
        self.stdout.write(f"Autoguardados borrados: {deleted} (sin cambios en {days} días).")
