# ACT-214B — Entorno de ejecución integrado v2.0

Base: IngeniaLab_ACT209.zip. Esta etiqueta identifica la revisión de entorno;
no equivale al release funcional v2.0-beta de ACT-214C ni a la demo de ACT-214.

## Instalación desde cero

Instala Python 3.12.x (incluye pip/venv), Java 17 o superior y Graphviz.
Agrega sus ejecutables al PATH. Comprueba `python --version`, `java -version`
y `dot -V` en una terminal nueva. En Windows el lanzador `py -3.12` selecciona
el intérprete. En Ubuntu instala además el paquete python3.12-venv si hace falta.
En macOS pueden instalarse mediante el gestor de paquetes habitual.
No se requiere Node para ejecutar Django; sí para las pruebas JS de ACT-209.

El cronograma menciona Java 11; la base ACT-207B/209 requiere Java 17+ y
conservamos ese mínimo. ACT-202 también menciona PlantUML 1.2024.7, mientras
que la base entregada fija 1.2026.2; conservamos 1.2026.2 y su SHA-256.
Esta desviación queda documentada; no se declara compatibilidad probada con
Java 11 ni con el JAR anterior.
SQLite viene con Python. El perfil local no requiere PostgreSQL.

Desde la carpeta `ingenialab` (contiene manage.py):

- Windows PowerShell: `py -3.12 scripts/setup_local.py`
- Linux/macOS: `python3.12 scripts/setup_local.py`
- Alternativas: `sh scripts/setup_local.sh` o `powershell -File scripts/setup_local.ps1`.

El script crea .venv si falta, instala versiones exactas, verifica pip, descarga
el JAR oficial fijado con SHA-256 y ejecuta verificaciones reales SVG/PNG/PDF.
Detiene la preparación si falla un comando. No instala Java/Graphviz por ti.
Necesita Internet para pip y el JAR. Para instalación sin Internet, prepara un
wheelhouse de las mismas versiones con `pip download -r requirements-test.txt
-d wheelhouse`, instala con `pip install --no-index --find-links wheelhouse
-r requirements-test.txt` y copia el JAR oficial a vendor/plantuml.jar.
Ejecuta después el verificador para comprobar su hash. No uses un JAR diferente.

## Arranque local

Linux/macOS (Windows: sustituye `.venv/bin/python` por `.venv\Scripts\python.exe`):

```sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_ingenialab
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Abre http://127.0.0.1:8000 y registra un estudiante. El seed es idempotente.
Migrate y seed modifican la BD local; respalda db.sqlite3 antes de aplicarlos
sobre datos propios. El verificador no migra ni siembra esa base.

## Verificación y evidencia por integrante

```sh
.venv/bin/python scripts/verify_environment.py --output var/act214b/mi-equipo.json
.venv/bin/python manage.py test apps integrations
```

El primer comando devuelve 0 sólo si todas las comprobaciones aplicables pasan;
1 si alguna falla. Registra plataforma, intérprete y versiones. Comprueba hash
JAR, Java, dot, requirements, pip check, SQLite temporal, Django, consistencia
de migraciones, SVG/PNG/caché reales y PDF con SVG real. No depende de un 500
ni acepta fallback de dibujo como resultado real. La latencia estricta se mide
por separado con `manage.py plantuml_check --strict`; no es una dependencia.

Conserva un JSON por integrante. El resultado de Linux incluido es evidencia
de este entorno, no de Windows/macOS ni de los equipos de todo el equipo.
No se marca realizada una verificación que nadie ha ejecutado.

## PDF e IA: dependencias reales

ReportLab + svglib son el motor implementado, no WeasyPrint. No se requieren
Pango/Cairo para el motor PDF ni un compilador LaTeX. Graphviz conserva
sus propias dependencias nativas de dibujo: instálalas con su distribución.
La prueba convierte SVG de PlantUML y
lo incrusta en el reporte. Pillow/lxml usan wheels cuando están disponibles;
si pip intenta compilarlos, instala sus herramientas de compilación o usa una
plataforma con wheels compatibles para Python 3.12.

Las entrevistas usan catálogo JSON/BD; no hay adaptador de proveedor IA ni SDK.
IA se registra NOT_APPLICABLE en esta base. No se añaden claves ficticias,
paquetes sin uso ni se declara probada la futura integración CU-06/CP-07.
PostgreSQL es opcional y queda fuera de este perfil (requiere su driver).
No cambies a ese backend sin preparar y validar sus dependencias.

## Resolución de problemas

- JAR ausente: `manage.py install_plantuml`; hash distinto: conserva una copia
  y recupera el JAR fijado. El instalador no sobrescribe un archivo diferente.
- Java/dot ausente: instala y revisa PATH o PLANTUML_JAVA / PLANTUML_DOT.
- PDF o importación falla: usa el Python de .venv y repite pip check.
- Red bloqueada: usa wheelhouse y JAR verificado como se indica arriba.
- Configuración externa: elimina variables POSTGRES_* para el perfil SQLite;
  conserva sólo las variables PLANTUML_* que apunten a tus instalaciones.
- Los reportes ACT-209 son históricos. Su antiguo estado parcial no se
  reinterpreta como fallo de instalación; la revisión documental cerró CU-02.
