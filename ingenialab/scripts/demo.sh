#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
for python in python3.12 python3.13 python3.11 python3; do
  if command -v "$python" >/dev/null 2>&1; then
    exec "$python" scripts/demo.py "$@"
  fi
done
echo 'Instala Python 3.11, 3.12 o 3.13.' >&2
exit 1
