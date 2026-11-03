# IngeniaLab 2.0 - ACT-221A

Empaquetado final de la versión 2.0 (WP.17). La distribución es el árbol de la
rama `it-2` (y después `main`) de este repositorio; comience por este archivo.

## Requisitos

Instale Python 3.12 (compatibles 3.11-3.13), Java 17+ y Graphviz. En Windows
habilite Python y Graphviz en PATH y abra una terminal nueva. Compruebe
`java -version` y `dot -V`. La primera preparación necesita Internet para
instalar dependencias y descargar el JAR de PlantUML (1.2026.2, verificado por
SHA-256). El JAR y la base `db.sqlite3` no se versionan en Git: se generan en
cada equipo.

## Instalación y arranque

Clone el repositorio (o descomprima la descarga de GitHub) en una carpeta nueva
y, desde la carpeta raíz IngeniaLab, ejecute:

- Windows: `iniciar_local.bat`
- Linux/macOS: `sh iniciar_local.sh`

El lanzador usa `ingenialab/scripts/demo.py`, que en cada arranque:

1. crea o repara `ingenialab/.venv` y reinstala dependencias si cambió
   `requirements.txt`;
2. instala el JAR de PlantUML si falta y comprueba Java y Graphviz;
3. aplica migraciones y carga `seed_ingenialab` (idempotente: escenarios,
   requisitos maestros, inspecciones y las ocho lecciones de modelado);
4. calienta PlantUML para acelerar el primer diagrama; si falla, muestra un
   aviso y continúa;
5. arranca el servidor en http://127.0.0.1:8000 con los seis módulos.

Abra esa URL y registre su cuenta. Detenga con Ctrl+C. En próximas sesiones
basta ejecutar el lanzador; tras un `git pull` también aplica las migraciones
nuevas. Use `--port 8001` si el puerto 8000 está ocupado. No se necesita
activar .venv. No copie una .venv de otro equipo.

El lanzador respeta las variables ya definidas en el entorno (modo IA, banco de
respuestas, `INGENIALAB_SQLITE_PATH`, `POSTGRES_DB`); solo fuerza los seis
módulos. Sin variables usa SQLite local y modo catálogo, que no requiere Ollama
ni API key. `.env.example` es referencia y no se carga automáticamente.

Para verificar el motor de diagramas por separado:

```sh
cd ingenialab
.venv/bin/python manage.py plantuml_check
```

En Windows use `.\.venv\Scripts\python.exe`. La opción `--strict` además exige
las metas de tiempo de RNF-03; puede fallar en equipos lentos aunque el motor
funcione.

## Contenido y uso

Consulte docs/GUIA_RELEASE_2_0.md para la operación actual. Los documentos
Word de docs/ se conservan como antecedentes. El README de ingenialab contiene
los detalles del banco de respuestas e IA opcional de esta versión;
ingenialab/README_ACT214C.md explica staging E2E.

Las pruebas ejecutadas y sus resultados se encuentran en evidencia/ACT221A/.
Se pueden reejecutar desde ingenialab/:

```sh
INGENIALAB_TEST_PLANTUML=1 .venv/bin/python manage.py test apps integrations
node tests/api-resilience.cjs
node tests/modeling-validation.cjs
.venv/bin/python scripts/e2e_staging.py
```

Node es opcional, solo se usa para pruebas JS. Sin `INGENIALAB_TEST_PLANTUML=1`
se omiten las pruebas Django del motor real. E2E crea una base aparte en
var/staging: no contiene sus usuarios reales.

## Respaldo y alcance

Detenga el servidor y respalde `ingenialab/db.sqlite3` antes de actualizar.
Esta entrega no publica un tag ni un release remoto, y no sustituye la
aceptación formal del equipo ni las evidencias de ACT-214/ACT-220.
