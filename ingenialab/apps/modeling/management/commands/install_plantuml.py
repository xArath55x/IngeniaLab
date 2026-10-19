"""Descarga una version fijada del JAR oficial; uso solo en instalacion."""
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError

URL="https://github.com/plantuml/plantuml/releases/download/v1.2026.2/plantuml-1.2026.2.jar"
SHA256="3cdce52133c424dea22425b947ae9d47f2167b0866dfcf99e714d4ea1689975c"
class Command(BaseCommand):
    help='Instala PlantUML 1.2026.2 en PLANTUML_JAR y verifica SHA-256.'
    def handle(self,*args,**options):
        target=Path(settings.PLANTUML_JAR)
        if target.exists():
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            if digest==SHA256: self.stdout.write('El JAR fijado ya esta instalado.');return
            raise CommandError('Ya existe otro JAR. Conserva una copia y elige otra ruta PLANTUML_JAR si deseas instalar la version fijada.')
        name=None
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            with urllib.request.urlopen(URL,timeout=60) as response, tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as out:
                name=out.name;digest=hashlib.sha256();size=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk: break
                    size+=len(chunk)
                    if size>50_000_000: raise ValueError('Descarga demasiado grande.')
                    digest.update(chunk);out.write(chunk)
            if digest.hexdigest()!=SHA256: raise ValueError('El SHA-256 no coincide; el JAR no se instalara.')
            os.replace(name,target)
        except Exception as e: raise CommandError(f'No se pudo instalar PlantUML: {e}. Puedes descargar el JAR oficial manualmente.') from e
        finally:
            if name:
                try: os.unlink(name)
                except FileNotFoundError: pass
        self.stdout.write(self.style.SUCCESS('PlantUML 1.2026.2 instalado y verificado. Ejecuta plantuml_check.'))
