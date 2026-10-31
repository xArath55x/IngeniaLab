@echo off
setlocal
cd /d "%~dp0ingenialab"
if not exist ".venv\Scripts\python.exe" (
 echo Prepare el entorno siguiendo LEEME_RELEASE.md.
 exit /b 1
)
set "INGENIALAB_MODULES=interviews,classification,modeling,inspection,reports,progress"
set "INGENIALAB_AI_MODE=catalog"
set "INGENIALAB_AI_FREE_ANSWERS=0"
set "INGENIALAB_AI_ANSWER_BANK=0"
set "INGENIALAB_DEBUG=1"
set "INGENIALAB_ALLOWED_HOSTS=localhost,127.0.0.1"
set "POSTGRES_DB="
set "INGENIALAB_SQLITE_PATH=%CD%\db.sqlite3"
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
