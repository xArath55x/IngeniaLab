@echo off
rem ACT-221A / ACT-317: arranque local de IngeniaLab 3.0.0. Delega en scripts\demo.ps1 (ACT-214), que prepara
rem .venv, PlantUML, migraciones y seed antes de levantar el servidor.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ingenialab\scripts\demo.ps1" %*
exit /b %ERRORLEVEL%
