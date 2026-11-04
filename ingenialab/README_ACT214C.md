# ACT-214C — Build preliminar de integración v2.0-beta

Entregable: etiqueta `release/v2.0-beta` y script automatizado de pruebas
end-to-end sobre una base de datos de staging. No se añaden dependencias ni
migraciones.

## Prueba end-to-end en staging

Desde `IngeniaLab/ingenialab`, con Java 17+ y Graphviz preparados:

```sh
.venv/bin/python scripts/e2e_staging.py
```

En Windows: `.venv\Scripts\python.exe scripts\e2e_staging.py`.

El script:

1. Crea una BD SQLite limpia en `var/staging/staging.sqlite3` (vía
   `INGENIALAB_SQLITE_PATH`), aplica migraciones y ejecuta `seed_ingenialab`.
   No toca `db.sqlite3` ni una base PostgreSQL: ignora las variables `POSTGRES_*`.
2. Levanta `runserver` con los seis módulos y el adaptador IA en modo catálogo.
3. Recorre por HTTP, con cookies y CSRF como el navegador:

| Paso | Qué verifica |
| --- | --- |
| CU-01 Entrevista | Registro, inicio de escenario, preguntas hasta finalizar (máx. 9) |
| CU-03 Clasificación | Declaraciones resaltables, retroalimentación, reclasificación sin duplicar, precisión 100 %, rechazo de categorías inválidas |
| CU-02 Modelado | Guardado del caso de uso y diagrama SVG con el motor PlantUML real |
| CU-04 Inspección | Hallazgo, pista, conclusión y bloqueo de la práctica concluida |
| Tablero | Puntos acumulados y navegación con los seis módulos |
| CU-05 Reporte | Descarga del PDF |
| Aislamiento | Una segunda cuenta no abre ni opera datos ajenos y no genera reporte |
| Sesión (RF-12) | Sin sesión, el tablero redirige al login y `/api/` responde 401 JSON |

Sale con código 0 si todo pasa. La evidencia queda en `var/staging/`
(ignorada por Git): `e2e_report.json` (commit, versión de Python, pasos y
tiempos), `reporte_e2e.pdf` y `server.log`.

El respaldo SVG no cuenta como integración real. En un equipo sin Java o
Graphviz se puede ejecutar con `--allow-plantuml-fallback`; el reporte lo
registra en `plantuml_fallback_permitido`. El CI usa esa opción porque no
instala el motor, y publica la evidencia como artefacto `e2e-staging-*`.

## Etiqueta release/v2.0-beta

Se crea sobre `it-2` cuando ACT-211A1 y ACT-211A2 están integradas y el
script pasa con el motor real:

```sh
git switch it-2 && git pull origin it-2
.venv/bin/python scripts/e2e_staging.py
git tag -a release/v2.0-beta -m "Build preliminar de integración v2.0-beta (ACT-214C)"
git push origin release/v2.0-beta
```
