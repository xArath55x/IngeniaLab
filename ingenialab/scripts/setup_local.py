"""Prepara .venv y verifica dependencias; no crea usuarios ni modifica datos."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info[:2] != (3, 12):
        print('Usa Python 3.12.x para este perfil reproducible.', file=sys.stderr)
        return 1
    target = ROOT / '.venv'
    if not target.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    python = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    commands = [
        [str(python), '-c', 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'],
        [str(python), '-m', 'pip', 'install', '-r', 'requirements-test.txt'],
        [str(python), '-m', 'pip', 'check'],
        [str(python), 'manage.py', 'install_plantuml'],
        [str(python), 'scripts/verify_environment.py'],
    ]
    try:
        for command in commands:
            subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        print('Preparacion incompleta. Corrige el error indicado y repite el comando.', file=sys.stderr)
        return exc.returncode
    print('Entorno verificado. Continua con migrate y seed_ingenialab segun README_ACT214B.md.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
