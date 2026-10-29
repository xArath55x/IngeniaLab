"""ACT-214: levanta la demo v2.0 en un paso (entorno, BD poblada y servidor).

Si no existe .venv, ejecuta primero setup_local.py. Despues aplica migraciones, carga
seed_ingenialab (idempotente) y arranca runserver con los seis modulos.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def main():
    parser = argparse.ArgumentParser(description='Levanta la demo v2.0 de IngeniaLab.')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--allow-plantuml-fallback', action='store_true',
                        help='acepta el respaldo SVG si no hay Java/Graphviz (solo para revisar la demo)')
    args = parser.parse_args()

    if not VENV_PYTHON.is_file():
        result = subprocess.run([sys.executable, 'scripts/setup_local.py'], cwd=ROOT)
        if result.returncode:
            return result.returncode

    env = dict(os.environ)
    if args.allow_plantuml_fallback:
        env['PLANTUML_ALLOW_FALLBACK'] = '1'
    python = str(VENV_PYTHON)
    try:
        for command in (['manage.py', 'migrate', '--noinput'], ['manage.py', 'seed_ingenialab']):
            subprocess.run([python, *command], cwd=ROOT, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        print('No se pudo preparar la base de datos. Corrige el error indicado y repite el comando.', file=sys.stderr)
        return exc.returncode

    print(f'Demo lista en http://127.0.0.1:{args.port}/ (registra una cuenta de estudiante). Ctrl+C para detener.')
    try:
        return subprocess.run([python, 'manage.py', 'runserver', f'127.0.0.1:{args.port}'], cwd=ROOT, env=env).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
