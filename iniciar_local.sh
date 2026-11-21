#!/bin/sh
# ACT-221A / ACT-317: arranque local de IngeniaLab 3.0.0. Delega en scripts/demo.sh (ACT-214), que prepara
# .venv, PlantUML, migraciones y seed antes de levantar el servidor.
set -eu
exec sh "$(dirname "$0")/ingenialab/scripts/demo.sh" "$@"
