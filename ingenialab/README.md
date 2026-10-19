# IngeniaLab — MVP

Plataforma web didáctica para practicar **elicitación, especificación (casos de uso + UML) e inspección de requisitos**.
Proyecto de Byte Force para la materia de Introducción a la Ingeniería de Software (UAZ), conforme al
SRS v1.2 (WP.13) y al SDS v1.0 (WP.16) — ISO/IEC 29110-5-1-2:2025, Perfil Básico.

## Inicio rápido (desarrollo)

Requisitos: Python 3.11+, Java 17+ y Graphviz (`dot` en PATH). ACT-207B usa el motor real de PlantUML con Graphviz para SVG y PNG.

```bash
cd ingenialab
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# PlantUML fijado, descargado con verificacion SHA-256
.venv/bin/python manage.py install_plantuml
.venv/bin/python manage.py plantuml_check --strict
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_ingenialab        # escenarios e inspecciones (idempotente)
.venv/bin/python manage.py runserver
```

Abre http://127.0.0.1:8000, regístrate como estudiante y comienza en **Elicitación**.
La base de datos de desarrollo incluida trae un usuario de demostración: `demo` / `demo12345`.

Pruebas automatizadas (evidencia para VR-01):

```bash
.venv/bin/python manage.py test apps integrations
```

## Flujo del estudiante (piloto: entrevistas y modelado)

Con ACT-207A están habilitados **entrevistas (CU-01)** y **modelado (CU-02)**. Para utilizar el formulario de modelado es necesario terminar al menos una entrevista:

1. El estudiante elige un escenario y se abre un chat estilo mensajería con el cliente virtual.
2. En cada turno se ofrecen **3 preguntas** en orden aleatorio: una muy útil (+10), una más o menos útil (+5)
   y una que no aporta (0). El cliente responde según la calidad de la pregunta.
3. La entrevista dura **hasta 9 preguntas**. Puede terminarse antes (con confirmación) o reiniciarse.
4. Al final se muestra el puntaje (máx. 90), una calificación formativa y la explicación de cada elección,
   con la mejor opción de cada ronda.

Los demás módulos (clasificación, inspección, reportes y tablero de progreso) siguen en el código y se
reactivan con la variable de entorno:

```bash
INGENIALAB_MODULES=interviews,classification,modeling,inspection,reports,progress
```

## Arquitectura (SDS §2)

| SCI | Paquete | Responsabilidad |
|---|---|---|
| SCI-01 | `apps/accounts` | Login/registro, `ApiSessionGuardMiddleware` (401 JSON en `/api/` sin sesión) |
| SCI-02 | `apps/interviews` | Escenarios versionados, `services.py` = InterviewEngine, bitácora |
| SCI-03 | `apps/classification` | `services.py` = RequirementService (upsert RF/RNF, precisión) |
| SCI-04 | `apps/modeling` | `validators.py` = ModelingValidator, casos de uso y diagramas |
| SCI-05 | `integrations/plantuml` | `builder.py` (spec → PlantUML), `service.py` (SVG/PNG real + caché SHA-256 atómica) |
| SCI-06 | `apps/inspection` | `services.py` = AuditEngine (hallazgos, pistas, precisión) |
| SCI-07 | `apps/progress` | `services.py` = GamificationService/ScoringEngine, tablero |
| SCI-08 | `integrations/pdf` | `generator.py` = PDFReportGenerator |
| UI | `templates/`, `static/` | Django Templates + JS nativo; `static/js/app.js` incluye el OfflineHandler (RF-12) |

Los escenarios viven en `data/interviews.json` (cada ronda: un tema con exactamente una opción `high`, una
`medium` y una `low`, cada una con su respuesta y su justificación) y los ejercicios de inspección en
`data/inspections.json`. Para agregar o modificar contenido edita el JSON y ejecuta `seed_ingenialab`. Una versión de escenario que ya tiene prácticas no se sobrescribe: publica una
versión nueva (`"version": "2.1"`) y la anterior se desactiva automáticamente.

## Trazabilidad de requisitos

| Requisito (SRS v1.2) | Implementación |
|---|---|
| RF-01 Entrevistas guiadas | `interviews/services.py` (`get_dialogue`, `finish_interview`, `reset_interview`) |
| RF-02 Captura y clasificación | `classification/services.py::classify_statement` + `UniqueConstraint` |
| RF-03 Retroalimentación | `MasterRequirement.feedback_explanation`, devuelta al confirmar |
| RF-04 Plantilla de casos de uso | `modeling/validators.py` |
| RF-05 Diagramas PlantUML | `integrations/plantuml/` |
| RF-06 Precisión | `classification/services.py::recalculate`, `inspection/services.py::compute` |
| RF-07 Gamificación | `progress/services.py` (puntos derivados del estado, niveles, insignias; pistas penalizan) |
| RF-08 Reporte PDF | `integrations/pdf/generator.py`, `progress/views.py::report_download` |
| RF-09 Autenticación | `apps/accounts` (Django Auth) |
| RF-10 Guardado y recuperación | Persistencia por usuario + «Retomar trabajo» en el tablero |
| RF-11 Inspección de defectos | `apps/inspection` |
| RF-12 Interrupciones | `static/js/app.js` (banner + reintento, modal de reautenticación) + middleware 401 |
| RNF-01/02 Usabilidad y accesibilidad | Instrucciones por pantalla, campos resaltados, retroalimentación con icono + texto, navegación con teclado |
| RNF-03 < 2 s | Caché SHA-256, timeout y mediciones con `plantuml_check --strict`; depende del equipo y tamaño del diagrama |
| RNF-05 Sesión segura | Expiración a 30 min de inactividad; HTTPS/HSTS/cookies seguras con `INGENIALAB_DEBUG=0` |
| RNF-06 Arquitectura modular | Capas separadas: vistas → servicios → ORM / adaptadores |

## Despliegue (producción)

Variables de entorno:

| Variable | Descripción |
|---|---|
| `INGENIALAB_SECRET_KEY` | Clave secreta de Django (obligatoria) |
| `INGENIALAB_DEBUG` | `0` en producción (activa HTTPS obligatorio, HSTS y cookies seguras) |
| `INGENIALAB_ALLOWED_HOSTS` | Dominios separados por coma |
| `INGENIALAB_CSRF_TRUSTED_ORIGINS` | Orígenes HTTPS confiables detrás de un proxy, p. ej. `https://ingenialab.uaz.edu.mx` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | Si `POSTGRES_DB` está definida se usa PostgreSQL 15+ (requiere `pip install psycopg[binary]`) |
| `PLANTUML_JAR`, `PLANTUML_JAVA`, `PLANTUML_CACHE_DIR` | Ubicación de PlantUML, Java y la caché de diagramas |

```bash
.venv/bin/pip install gunicorn "psycopg[binary]"
.venv/bin/python manage.py migrate && .venv/bin/python manage.py seed_ingenialab
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/gunicorn config.wsgi --bind 0.0.0.0:8000
```

Sirve detrás de un proxy inverso con TLS (Nginx/Caddy) que envíe `X-Forwarded-Proto`.
Si Java, Graphviz o el JAR no están disponibles, se muestra un error explicativo y no se guarda un diagrama falso. El respaldo heredado solo se activa explícitamente con `PLANTUML_ALLOW_FALLBACK=1`, para demostración; no cuenta como generación real.

## Decisiones respecto al SDS

- **PDF con ReportLab en lugar de WeasyPrint:** WeasyPrint requiere Pango/Cairo instalados en el sistema; ReportLab
  es Python puro. La interfaz `build_report()` aísla el motor, por lo que puede cambiarse sin tocar las vistas.
- **SQLite en desarrollo**, PostgreSQL en producción vía variables de entorno (mismo ORM y migraciones).
- **Fuera de alcance (SRS §2):** panel docente, edición gráfica libre, modo offline y colaboración en tiempo real.

## Actividad ACT-207A integrada

El formulario de `apps/modeling/` utiliza Django Forms y validación JavaScript con los mismos límites.
Abre **Modelado → Nuevo caso de uso** después de finalizar una entrevista. **Validar plantilla** comprueba
los campos sin invocar PlantUML; generar y guardar utilizan el motor que ya incluía el proyecto.
Se exige nombre, actor principal, precondiciones, postcondiciones y al menos dos pasos con texto.
Los números 1..n se derivan del orden de la lista y se actualizan al agregar o quitar filas.

Consulta `../ACT-207A_CAMBIOS.txt` para ver todos los archivos agregados/modificados, decisiones,
instrucciones de instalación en Windows y las pruebas ejecutadas. No se requiere una migración nueva.

Si tienes definida `INGENIALAB_MODULES`, incluye `modeling`; una variable previamente configurada
sigue teniendo prioridad sobre el valor por defecto de esta entrega.

Pruebas específicas:

```bash
python manage.py test apps.modeling
# Opcional, solo si tienes Node.js: no requiere npm install
node tests/modeling-validation.cjs
```

## ACT-207B: motor real de diagramas

Tras instalar Java 17+ y Graphviz, ejecuta `python manage.py install_plantuml` y
`python manage.py plantuml_check --strict`. El primer comando requiere Internet
para instalar PlantUML 1.2026.2 con SHA-256 verificado; después se genera localmente.
El JAR no se incluye en el ZIP. La descarga manual oficial también es válida.

En Modelado puedes elegir vista previa SVG o PNG y pulsar **Validar y generar diagrama**.
La pantalla indica el tiempo y si se reutilizó la caché. Guarda para habilitar las
descargas de la versión persistida. Cambios pendientes no aparecen en esas descargas.

Se conservan los formularios y validaciones de ACT-207A. No hay migraciones nuevas.
Los casos antiguos deben regenerarse y guardarse para usar el builder actualizado.

Configuración adicional: `PLANTUML_DOT` (ruta o nombre de dot), `PLANTUML_TIMEOUT`
(presupuesto por operación, 1.8 s por defecto) y `PLANTUML_ALLOW_FALLBACK` (0 por defecto).
La caché distingue formato, versión del adaptador y configuración del motor. Las
entradas antiguas quedan ignoradas; se pueden borrar con el servidor detenido.

Pruebas con Java/Graphviz/JAR configurados, en PowerShell:

```powershell
$env:INGENIALAB_TEST_PLANTUML = "1"
.\.venv\Scripts\python.exe manage.py test apps integrations
.\.venv\Scripts\python.exe manage.py plantuml_check --runs 3 --strict
```

Sin esa variable, las tres pruebas de integración que requieren Java se omiten
explícitamente. Las pruebas generales usan el respaldo o dobles de prueba donde
corresponde; eso no cambia el modo normal de la aplicación.

Consulta `../ACT-207B_CAMBIOS.txt` para instrucciones completas de Windows y
`../docs/ACT-207B_Mediciones.json` para las muestras del entorno de validación.
