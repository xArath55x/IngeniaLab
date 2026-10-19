"""Diagnostico y medicion real de ACT-207B. No modifica practicas del usuario."""
import json
import tempfile
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.test.utils import override_settings
from integrations.plantuml.builder import build_usecase_diagram
from integrations.plantuml.service import render,PlantUMLError

SPEC={'name':'Registrar préstamo','system_name':'Biblioteca UAZ', 'primary_actors':['Bibliotecario'], 'secondary_actors':['Servicio de correo'], 'relations':[{'type':'include','target':'Verificar disponibilidad'},{'type':'extend','target':'Notificar rechazo'}]}
class Command(BaseCommand):
    help='Genera SVG y PNG reales, comprueba cache y mide tiempos (<2s / cache <50ms).'
    def add_arguments(self,parser):
        parser.add_argument('--runs',type=int,default=3)
        parser.add_argument('--output',help='Archivo JSON opcional con resultados.')
        parser.add_argument('--strict',action='store_true',help='Falla si alguna muestra no cumple las metas de tiempo.')
    def handle(self,*args,**options):
        if not 1 <= options['runs'] <= 20: raise CommandError('Usa entre 1 y 20 repeticiones.')
        samples=[]
        try:
            with tempfile.TemporaryDirectory() as cache, override_settings(PLANTUML_CACHE_DIR=cache,PLANTUML_ALLOW_FALLBACK=False):
                for i in range(options['runs']):
                    code=build_usecase_diagram({**SPEC,'name':f'Registrar préstamo {i+1}'})
                    for format in ('svg','png'):
                        cold=render(code,format);warm=render(code,format)
                        if cold.cached or not warm.cached or cold.data!=warm.data: raise CommandError('La cache no reprodujo el contenido esperado.')
                        sample={'format':format,'run':i+1,'code_hash':cold.code_hash,'generation_ms':cold.duration_ms,'cache_ms':warm.duration_ms,'generation_under_2s':cold.duration_ms<2000,'cache_under_50ms':warm.duration_ms<50,'bytes':len(cold.data)}
                        samples.append(sample);self.stdout.write(f'{format.upper()} {i+1}: generar={cold.duration_ms:.3f} ms; cache={warm.duration_ms:.3f} ms; {len(cold.data)} bytes')
        except PlantUMLError as e: raise CommandError(f'{e.code}: {e}') from e
        report={'engine':'plantuml','layout':'graphviz','samples':samples,'all_targets_met':all(s['generation_under_2s'] and s['cache_under_50ms'] for s in samples)}
        if options['output']:
            target=Path(options['output']);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if options['strict'] and not report['all_targets_met']: raise CommandError('El motor funciona, pero las muestras no cumplieron todas las metas de tiempo.')
        self.stdout.write(self.style.SUCCESS('SVG/PNG reales y cache SHA-256 verificados.'))
