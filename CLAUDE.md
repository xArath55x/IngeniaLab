# CLAUDE.md

Contexto para Claude Code al trabajar en este repositorio.

## Proyecto

IngeniaLab es una plataforma web didáctica (Django) para practicar elicitación, especificación (casos de uso + UML) e
inspección de requisitos. Es un proyecto escolar del equipo Byte Force (UAZ), desarrollado bajo ISO/IEC 29110 Perfil
Básico. El código, los comentarios, la UI y la documentación están **en español**; mantén ese idioma.

Los identificadores del SRS v1.2 y el SDS v1.0 aparecen en docstrings y comentarios: `CU-xx` (casos de uso),
`RF-xx` / `RNF-xx` (requisitos), `SCI-xx` (componentes de diseño), `VR-01` (verificación). Consérvalos al modificar
código y úsalos en commits y PRs cuando aplique. La tabla de trazabilidad está en `ingenialab/README.md`.

## Estructura

- `ingenialab/`: proyecto Django. **Todos los comandos de `manage.py` se ejecutan desde aquí.**
- `docs/`: Manual de Usuario y Guía de Operación (.docx).
- `USO_DEL_REPO.md`: flujo de Git del equipo. Léelo antes de crear ramas, commits o PRs.
- `.github/workflows/ci.yml`: CI (Python 3.11, 3.12 y 3.13).

## Comandos

```bash
cd ingenialab
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_ingenialab      # idempotente; carga data/*.json
.venv/bin/python manage.py runserver

.venv/bin/python manage.py test apps integrations  # toda la suite
.venv/bin/python manage.py test apps.progress.tests.<Clase>.<test>   # una sola prueba
.venv/bin/python manage.py makemigrations --check --dry-run          # el CI falla si falta una migración
```

## Arquitectura

Capas: **vistas → servicios → ORM / adaptadores**. La lógica de negocio va en `services.py` (o `validators.py`
en modeling), no en las vistas.

| Paquete | Rol |
| --- | --- |
| `apps/accounts` | Login/registro y los middlewares `ApiSessionGuardMiddleware` y `ModuleGateMiddleware` |
| `apps/interviews` | Escenarios versionados y motor de entrevista (`services.py`); contiene el comando `seed_ingenialab` |
| `apps/classification` | Clasificación RF/RNF y cálculo de precisión |
| `apps/modeling` | Casos de uso; `validators.py` normaliza y valida la especificación |
| `apps/inspection` | Ejercicios de inspección, hallazgos y pistas |
| `apps/progress` | Puntos, niveles, insignias, tablero (`/`) y reporte PDF |
| `integrations/plantuml` | `builder.py` (spec → PlantUML) y `service.py` (render con caché SHA-256 y respaldo SVG) |
| `integrations/pdf` | `build_report()` con ReportLab |

Rutas raíz (`config/urls.py`): `/cuentas/`, `/elicitacion/`, `/clasificacion/`, `/modelado/`, `/inspeccion/`, `/` (tablero).

## Cosas no obvias

- **Módulos deshabilitados por defecto.** `interviews` y `modeling` están activos. `ModuleGateMiddleware` redirige los demás
  a la lista de escenarios (o responde 404 JSON en `/api/`). Para probarlos:
  `INGENIALAB_MODULES=interviews,classification,modeling,inspection,reports,progress`.
  Las pruebas ejercitan todos los módulos, así que no asumas que el código inactivo está muerto.
- **Endpoints JSON bajo `/api/`.** Cualquier ruta que contenga `/api/` y no tenga sesión recibe un **401 JSON**
  (no una redirección), para que `static/js/app.js` muestre el modal de reautenticación (RF-12).
  Mantén esa convención en endpoints nuevos.
- **El contenido vive en JSON.** Los escenarios están en `data/interviews.json` y las inspecciones en
  `data/inspections.json`. Cada ronda debe tener exactamente una opción `high`, una `medium` y una `low`.
  Una versión de escenario con prácticas no se sobrescribe: publica una nueva `"version"` y la anterior se desactiva.
- **Entrevista:** máximo 9 preguntas (`MAX_QUESTIONS`); +10 / +5 / 0 puntos según la calidad. El orden de las
  opciones es aleatorio pero estable por intento (semilla `intento:ronda`).
- **Sesión:** expira a los 30 min de inactividad. Con `INGENIALAB_DEBUG=0` se activan HTTPS, HSTS y cookies seguras.
- **Motor real PlantUML.** Java 17+ y Graphviz son necesarios para la verificación completa.
  El instalador fija PlantUML 1.2026.2 y verifica SHA-256. El fallback está deshabilitado
  por defecto y no se acepta como prueba de integración real. No subir JAR a Git;
  en CI se recupera con `manage.py install_plantuml`.
- **Pruebas:** están en `apps/progress/tests.py`, `apps/progress/test_pdf.py`,
  `apps/modeling/tests.py`, `apps/modeling/test_plantuml.py`, `apps/inspection/tests.py`
  e `integrations/plantuml/tests.py`. Ejecutar `manage.py test apps integrations`.
  Definir `INGENIALAB_TEST_PLANTUML=1` para incluir el motor real. Mantener el
  contenido pedagógico y las pruebas existentes de ACT-208D.
- **Entorno ACT-214B:** consultar `ingenialab/README_ACT214B.md`. La preparación
  se ejecuta con `python scripts/setup_local.py`; la evidencia de instalación no
  sustituye la ejecución de la suite ni la validación en cada equipo.


## Flujo de Git (resumen de `USO_DEL_REPO.md`)

- Ramas de tarea desde la rama de iteración vigente (`it-N`, hoy `it-2`), con nombre `tipo/descripcion`
  (`feature/`, `fix/`, `docs/`, `refactor/`, `test/`).
- PRs siempre hacia `it-N`, nunca directo a `main`. `main` solo recibe `it-N` al cierre de la iteración.
- Commits con verbo en infinitivo y mayúscula inicial, sin punto final: `Agregar reinicio de entrevista (CU-01)`.
- Al integrar `it-N` en `main`, no borres `it-N`.
