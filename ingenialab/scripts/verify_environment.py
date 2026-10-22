"""ACT-214B: diagnostico reproducible sin alterar la base de datos del alumno."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'var/act214b/environment.json'))
    args = parser.parse_args()
    results = []

    def check(name, action):
        try:
            detail = action()
            results.append({'check': name, 'status': 'PASS', 'detail': detail})
        except Exception as exc:
            results.append({'check': name, 'status': 'FAIL', 'detail': str(exc)})

    def command(argv):
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60)
        if p.returncode:
            raise RuntimeError((p.stdout + p.stderr)[-3000:])
        return (p.stdout + p.stderr).strip()

    def python_version():
        if not (3, 11) <= sys.version_info[:2] <= (3, 13):
            raise RuntimeError('Se requiere Python 3.11, 3.12 o 3.13. Perfil validado localmente: 3.12.x.')
        return platform.python_version()

    def requirements():
        versions = {}
        for line in (ROOT / 'requirements.txt').read_text().splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            name, expected = line.split('==')
            actual = importlib.metadata.version(name)
            if actual != expected:
                raise RuntimeError(f'{name}: instalado {actual}, requerido {expected}')
            versions[name] = actual
        return versions

    check('python', python_version)
    check('requirements', requirements)
    check('pip_check', lambda: command([sys.executable, '-m', 'pip', 'check']))

    def setup():
        import django
        django.setup()
        return django.get_version()
    check('django_setup', setup)
    try:
        from django.conf import settings
        settings.INSTALLED_APPS
    except Exception as exc:
        settings = type('UnavailableSettings', (), {'PLANTUML_JAVA': 'java', 'PLANTUML_DOT': 'dot', 'PLANTUML_JAR': str(ROOT / 'vendor/plantuml.jar')})()

    def java():
        output = command([settings.PLANTUML_JAVA, '-version'])
        match = re.search(r'version "(\d+)', output)
        if not match or int(match[1]) < 17:
            raise RuntimeError('El perfil actual requiere Java 17+ (el cronograma menciona Java 11).')
        return output
    check('java', java)
    check('graphviz', lambda: command([settings.PLANTUML_DOT, '-V']))

    def jar():
        from apps.modeling.management.commands.install_plantuml import SHA256
        digest = hashlib.sha256(Path(settings.PLANTUML_JAR).read_bytes()).hexdigest()
        if digest != SHA256:
            raise RuntimeError('plantuml.jar no coincide con el SHA-256 fijado por el instalador.')
        return digest
    check('plantuml_integrity', jar)

    def sqlite():
        import sqlite3
        if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
            raise RuntimeError('Este perfil local exige SQLite; elimina POSTGRES_DB de la configuracion.')
        with sqlite3.connect(':memory:') as db:
            db.execute('create table probe (value text)')
            db.execute('insert into probe values (?)', ('IngeniaLab',))
            assert db.execute('select value from probe').fetchone()[0] == 'IngeniaLab'
        return sqlite3.sqlite_version
    check('sqlite', sqlite)
    check('django_check', lambda: command([sys.executable, 'manage.py', 'check']))
    check('migration_consistency', lambda: command([sys.executable, 'manage.py', 'makemigrations', '--check', '--dry-run']))

    def clean_database():
        # Configurar antes de django.setup en un proceso separado evita tocar db.sqlite3.
        with tempfile.TemporaryDirectory() as tmp:
            code = """import sys
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': sys.argv[1]}}
import django
django.setup()
from django.core.management import call_command
from apps.interviews.models import InterviewQuestion
call_command('migrate', interactive=False, verbosity=0)
call_command('seed_ingenialab', verbosity=0)
first = InterviewQuestion.objects.count()
call_command('seed_ingenialab', verbosity=0)
second = InterviewQuestion.objects.count()
if not first or first != second:
    raise RuntimeError('La carga semilla no es idempotente o no creo preguntas.')
print('Migraciones y semilla idempotente en SQLite temporal; preguntas:', second)
"""
            return command([sys.executable, '-c', code, str(Path(tmp) / 'clean.sqlite3')])
    check('clean_database_and_seed', clean_database)
    check('real_svg_png_cache', lambda: command([sys.executable, 'manage.py', 'plantuml_check', '--runs', '1']))

    def pdf():
        from integrations.pdf.generator import build_report, _svg_flowable
        from django.contrib.auth.models import User
        from integrations.plantuml.service import render
        from django.test.utils import override_settings
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as cache, override_settings(PLANTUML_CACHE_DIR=cache, PLANTUML_ALLOW_FALLBACK=False):
            svg = render('@startuml\nactor Alumno\nAlumno --> (Practicar)\n@enduml', 'svg').svg
            drawing = _svg_flowable(svg, 400)
            if drawing is None or not drawing.width or not drawing.height:
                raise RuntimeError('No se pudo convertir el SVG real con svglib.')
            uc = SimpleNamespace(name='Practicar', system_name='IngeniaLab', actors={'primary':['Alumno']}, preconditions='Sesion iniciada', main_flow=['Practicar'], alternate_flows=[], postconditions='Practica registrada', relations=[], diagram=SimpleNamespace(svg=svg))
            data = build_report(report_id='ACT214B', user=User(username='verificacion'), level={'number':1,'name':'Inicial'}, points=0, attempts=[], use_cases=[uc], inspections=[])
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-100:]:
            raise RuntimeError('PDF no valido')
        return {'bytes':len(data), 'includes_real_plantuml_svg':True, 'engine':'ReportLab + svglib'}
    check('integrated_pdf', pdf)
    results.append({'check':'ai', 'status':'NOT_APPLICABLE', 'detail':'Entrevistas por catalogo; esta base no contiene adaptador ni SDK de proveedor IA. No se valida una IA en vivo.'})
    report = {'activity':'ACT-214B', 'version':'ACT-214B-entorno-v2.0-base-08c036e', 'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'platform':platform.platform(), 'executable':sys.executable, 'ok':all(r['status'] != 'FAIL' for r in results), 'results':results}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for result in results:
        print(f"{result['status']}: {result['check']} — {result['detail']}")
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
