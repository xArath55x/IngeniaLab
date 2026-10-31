#!/bin/sh
set -eu
cd "$(dirname "$0")/ingenialab"
if [ ! -x .venv/bin/python ]; then
 echo "Prepare el entorno siguiendo LEEME_RELEASE.md."
 exit 1
fi
export INGENIALAB_MODULES=interviews,classification,modeling,inspection,reports,progress
export INGENIALAB_AI_MODE=catalog
export INGENIALAB_AI_FREE_ANSWERS=0
export INGENIALAB_AI_ANSWER_BANK=0
export INGENIALAB_DEBUG=1
export INGENIALAB_ALLOWED_HOSTS=localhost,127.0.0.1
unset POSTGRES_DB
export INGENIALAB_SQLITE_PATH="$PWD/db.sqlite3"
exec .venv/bin/python manage.py runserver 127.0.0.1:8000
