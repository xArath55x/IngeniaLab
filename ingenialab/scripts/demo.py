"""ACT-214: levanta la demo v2.0 en un paso (entorno, BD poblada y servidor).

Crea o repara .venv, reinstala las dependencias si cambio requirements.txt, instala el JAR de
PlantUML si falta, aplica migraciones, carga seed_ingenialab (idempotente) y arranca runserver
con los seis modulos.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / '.venv'
VENV_PYTHON = VENV / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
# Huella de requirements.txt instalada; si cambia tras un git pull, se reinstalan las dependencias.
STAMP = VENV / 'ingenialab-requirements.sha256'
MODULES = 'interviews,classification,modeling,inspection,reports,progress'


class StepError(Exception):
    pass


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError('usa un puerto entre 1 y 65535')
    return number


def run(label, command, env):
    try:
        subprocess.run(command, cwd=ROOT, env=env, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise StepError(f'Fallo: {label}. Corrige el error indicado arriba y repite el comando.') from exc


def prepare(env, allow_fallback):
    if VENV.exists() and not VENV_PYTHON.is_file():
        raise StepError('La .venv existente no corresponde a este sistema o esta incompleta. '
                        'Renombrala como respaldo y repite; no se eliminara automaticamente.')
    if not VENV.exists():
        if not (3, 11) <= sys.version_info[:2] <= (3, 13):
            raise StepError('Usa Python 3.11, 3.12 o 3.13 para crear la .venv.')
        venv.EnvBuilder(with_pip=True).create(VENV)
    python = str(VENV_PYTHON)

    # Se comprueba que Django importe, no solo que exista el interprete: un pip install fallido deja la .venv a medias.
    digest = hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()
    importable = subprocess.run([python, '-c', 'import django'], cwd=ROOT, capture_output=True).returncode == 0
    if not importable or not STAMP.is_file() or STAMP.read_text().strip() != digest:
        run('instalar dependencias (requiere red)', [python, '-m', 'pip', 'install', '-r', 'requirements.txt'], env)
        run('verificar dependencias', [python, '-m', 'pip', 'check'], env)
        STAMP.write_text(digest + '\n')

    # Idempotente: si el JAR fijado ya esta y su SHA-256 coincide, no descarga nada.
    try:
        run('instalar PlantUML', [python, 'manage.py', 'install_plantuml'], env)
    except StepError:
        if not allow_fallback:
            raise
        print('Sin PlantUML: los diagramas usaran el respaldo SVG.', file=sys.stderr)
    if not allow_fallback:
        missing = [name for name, cmd in (('Java', env.get('PLANTUML_JAVA', 'java')), ('Graphviz', env.get('PLANTUML_DOT', 'dot')))
                   if not shutil.which(cmd)]
        if missing:
            raise StepError(f'Falta {" y ".join(missing)} para generar diagramas. Instalalo o repite con '
                            '--allow-plantuml-fallback (respaldo SVG; no cuenta como integracion real).')


def main():
    parser = argparse.ArgumentParser(description='Levanta la demo v2.0 de IngeniaLab.')
    parser.add_argument('--port', type=port, default=8000)
    parser.add_argument('--allow-plantuml-fallback', action='store_true',
                        help='acepta el respaldo SVG si no hay Java/Graphviz (solo para revisar la demo)')
    args = parser.parse_args()

    env = dict(os.environ)
    # La demo siempre muestra los seis modulos, aunque el entorno limite INGENIALAB_MODULES.
    env['INGENIALAB_MODULES'] = MODULES
    if args.allow_plantuml_fallback:
        env['PLANTUML_ALLOW_FALLBACK'] = '1'
    python = str(VENV_PYTHON)
    try:
        prepare(env, args.allow_plantuml_fallback)
        run('aplicar migraciones', [python, 'manage.py', 'migrate', '--noinput'], env)
        run('cargar seed_ingenialab', [python, 'manage.py', 'seed_ingenialab'], env)
    except StepError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'No se pudo preparar el entorno: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    print(f'Iniciando la demo en http://127.0.0.1:{args.port}/ (registra una cuenta de estudiante). Ctrl+C para detener.')
    try:
        return subprocess.run([python, 'manage.py', 'runserver', f'127.0.0.1:{args.port}'], cwd=ROOT, env=env).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
