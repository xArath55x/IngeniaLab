# IngeniaLab

[![CI](https://github.com/adriariasd/IngeniaLab/actions/workflows/ci.yml/badge.svg)](https://github.com/adriariasd/IngeniaLab/actions/workflows/ci.yml)

Plataforma web didáctica para practicar **elicitación, especificación (casos de uso + UML) e inspección de requisitos**.
Proyecto del equipo **Byte Force** para la materia de Introducción a la Ingeniería de Software (UAZ), desarrollado conforme
a ISO/IEC 29110-5-1-2:2025, Perfil Básico.

## Descripción del producto

IngeniaLab permite que los estudiantes practiquen las actividades de ingeniería de requisitos con un cliente virtual y
reciban retroalimentación inmediata.

- **Entrevistas guiadas (CU-01):** el estudiante elige un escenario y conversa en un chat con un cliente virtual. En cada
  turno elige entre 3 preguntas: una muy útil (+10), una más o menos útil (+5) y una que no aporta (0). El cliente responde
  según la calidad de la pregunta. La entrevista dura hasta 9 preguntas y al final muestra el puntaje (máx. 90), una
  calificación formativa y la explicación de cada elección.
- **Clasificación de requisitos:** captura y clasificación de requisitos funcionales y no funcionales, con precisión calculada.
- **Modelado:** plantilla de casos de uso y generación de diagramas UML con PlantUML.
- **Inspección:** detección de defectos en especificaciones, con pistas y precisión.
- **Progreso y reportes:** puntos, niveles, insignias y reporte descargable en PDF.

> **Versión piloto:** solo el módulo de entrevistas está habilitado por defecto. Los demás se activan con la variable de
> entorno `INGENIALAB_MODULES` (ver abajo).

**Tecnologías:** Python 3.11+, Django 5.1, SQLite (desarrollo) / PostgreSQL (producción), PlantUML, ReportLab.

## Estructura del repositorio

| Carpeta / archivo  | Contenido                                                       |
| ------------------ | --------------------------------------------------------------- |
| `ingenialab/`      | Proyecto Django. Su [README](ingenialab/README.md) tiene la arquitectura, la trazabilidad de requisitos y el despliegue en producción. |
| `docs/`            | Manual de Usuario y Guía de Operación.                          |
| `USO_DEL_REPO.md`  | Guía de trabajo con Git y GitHub para el equipo.                |

## Cómo levantar el proyecto (desarrollo)

### Requisitos

- **Python 3.11 o superior**
- **Git**
- **Java 11 o superior** (opcional, solo para los diagramas PlantUML). Sin Java, el sistema usa un renderizador SVG de
  respaldo. Graphviz no es necesario.

### Pasos

1. Clona el repositorio y entra a la carpeta del proyecto Django:

   ```bash
   git clone https://github.com/adriariasd/IngeniaLab.git
   cd IngeniaLab/ingenialab
   ```

2. Crea el entorno virtual e instala las dependencias:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

   En Windows usa `.venv\Scripts\pip` y `.venv\Scripts\python` en lugar de `.venv/bin/...`.

3. (Opcional) Descarga PlantUML para generar diagramas:

   ```bash
   mkdir -p vendor
   curl -L -o vendor/plantuml.jar https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar
   ```

4. Crea la base de datos y carga los escenarios e inspecciones:

   ```bash
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py seed_ingenialab
   ```

   `seed_ingenialab` se puede ejecutar varias veces sin duplicar datos.

5. Inicia el servidor:

   ```bash
   .venv/bin/python manage.py runserver
   ```

6. Abre <http://127.0.0.1:8000>, **regístrate como estudiante** y comienza en **Elicitación**.

   Si necesitas acceso al panel de administración (`/admin`), crea un superusuario:

   ```bash
   .venv/bin/python manage.py createsuperuser
   ```

### Activar todos los módulos

Por defecto solo está habilitado el módulo de entrevistas. Para activar el resto, define la variable antes de iniciar el servidor:

```bash
INGENIALAB_MODULES=interviews,classification,modeling,inspection,reports,progress .venv/bin/python manage.py runserver
```

### Ejecutar las pruebas

```bash
.venv/bin/python manage.py test apps
```

## Documentación

- [Manual de Usuario](docs/Byte%20Force%20-%20Manual%20de%20Usuario%20v1.0%20-%20IngeniaLab.docx)
- [Guía de Operación](docs/Byte%20Force%20-%20Guia%20de%20Operacion%20v1.0%20-%20IngeniaLab.docx)
- [Arquitectura, trazabilidad y despliegue](ingenialab/README.md)
- [Guía de uso del repositorio](USO_DEL_REPO.md)

## ACT-211C — Correcciones de integración

Consulta [README_ACT211C.md](ingenialab/README_ACT211C.md) para errores corregidos,
reintentos, renovación CSRF, presupuestos de PlantUML y pruebas de regresión.
