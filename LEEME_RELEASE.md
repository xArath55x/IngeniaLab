# IngeniaLab 2.0 - ACT-221A actualizada

Distribución construida exclusivamente sobre IngeniaLab(2).zip.
Comience por este archivo; la revisión anterior no es la base de este paquete.

## Instalación desde cero

Instale Python 3.12 (compatibles 3.11-3.13), Java 17+ y Graphviz. En Windows
habilite Python y Graphviz en PATH y abra una terminal nueva. Compruebe
`java -version` y `dot -V`. Internet se necesita para instalar dependencias.
El JAR PlantUML está incluido con sus avisos de licencia.

Descomprima todo el ZIP en una carpeta nueva. Desde IngeniaLab/ingenialab:

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py plantuml_check --strict
```

Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python manage.py migrate
.venv/bin/python manage.py plantuml_check --strict
```

La base SQLite incluida ya está migrada y precargada con catálogos y
lecciones. No tiene cuentas, sesiones ni prácticas. Registre su cuenta al
abrir la aplicación. Si parte de una base vacía ejecute `manage.py
seed_ingenialab` con el mismo Python de .venv.

## Arranque

Desde la carpeta IngeniaLab ejecute `iniciar_local.bat` (Windows) o
`sh iniciar_local.sh` (Linux). Abra http://127.0.0.1:8000 y regístrese.
Los lanzadores habilitan los seis módulos, SQLite local y modo catálogo.
Detenga con Ctrl+C. En próximas sesiones basta ejecutar el lanzador.
No se necesita activar .venv. No copie una .venv de otro equipo.
.env.example es referencia y no se carga automáticamente.

## Contenido y uso

Consulte docs/GUIA_RELEASE_2_0.md para la operación actual. Los documentos
Word originales están integrados y se conservan como antecedentes. El
README de ingenialab contiene los detalles del banco de respuestas e IA
opcional de esta versión; README_ACT214C.md explica staging E2E.

Las pruebas ejecutadas y sus resultados se encuentran en evidencia/ACT221A/.
Las pruebas originales siguen incluidas y se pueden reejecutar:

```sh
.venv/bin/python manage.py test apps integrations
node tests/api-resilience.cjs
node tests/modeling-validation.cjs
.venv/bin/python scripts/e2e_staging.py
```

En Windows cambie el ejecutable por .\.venv\Scripts\python.exe. Node es
opcional, solo se usa para pruebas JS. Defina INGENIALAB_TEST_PLANTUML=1
para habilitar las pruebas Django del motor real. E2E crea una base aparte
en var/staging: no contiene sus usuarios reales.

## Respaldo y alcance

No sobrescriba una base personal con la base didáctica de este paquete.
Detenga el servidor y respalde db.sqlite3 antes de actualizar. Esta
entrega es local; no se publicó un tag ni un release remoto, y no sustituye
la aceptación formal del equipo ni las evidencias de ACT-214/ACT-220.
