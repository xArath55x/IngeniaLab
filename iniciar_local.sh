#!/bin/sh
# ACT-221A: arranque local de la release 2.0. Delega en scripts/demo.sh (ACT-214), que prepara
# .venv, PlantUML, migraciones y seed antes de levantar el servidor.
set -eu
exec sh "$(dirname "$0")/ingenialab/scripts/demo.sh" "$@"
