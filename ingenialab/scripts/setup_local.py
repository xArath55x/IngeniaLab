"""Prepara .venv y verifica dependencias; no crea usuarios ni modifica datos."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print('Usa Python 3.11, 3.12 o 3.13; esta entrega se valida localmente con 3.12.x.', file=sys.stderr)
        return 1
    target = ROOT / '.venv'
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if target.exists() and not python.is_file():
        print('La .venv existente no corresponde a este sistema o esta incompleta. Renombrala como respaldo y repite; no se eliminara automaticamente.', file=sys.stderr)
        return 1
    if not target.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    commands = [
        [str(python), '-c', 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)'],
        [str(python), '-m', 'pip', 'install', '-r', 'requirements.txt'],
        [str(python), '-m', 'pip', 'check'],
        [str(python), 'manage.py', 'install_plantuml'],
        [str(python), 'scripts/verify_environment.py'],
    ]
    try:
        for command in commands:
            subprocess.run(command, cwd=ROOT, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print('Preparacion incompleta. Corrige el error indicado y repite el comando.', file=sys.stderr)
        return getattr(exc, 'returncode', 1)
    print('Entorno verificado. Continua con migrate y seed_ingenialab segun README_ACT214B.md.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
