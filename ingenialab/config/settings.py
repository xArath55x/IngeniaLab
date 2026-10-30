"""Configuración de IngeniaLab (Byte Force).

Los valores sensibles se leen de variables de entorno. Ver README.md.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("INGENIALAB_SECRET_KEY", "dev-insecure-cambiar-en-produccion")
DEBUG = os.environ.get("INGENIALAB_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("INGENIALAB_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Orígenes HTTPS confiables para formularios detrás de un proxy, p. ej. https://ingenialab.uaz.edu.mx
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("INGENIALAB_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.interviews",
    "apps.classification",
    "apps.modeling",
    "apps.inspection",
    "apps.progress",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.ApiSessionGuardMiddleware",
    "apps.accounts.middleware.ApiRequestGuardMiddleware",
    "apps.accounts.middleware.ModuleGateMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.progress.context_processors.progress_summary",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Persistencia: SQLite por defecto para desarrollo; PostgreSQL 15+ en producción (SDS §2.1).
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # ACT-214C: el script E2E apunta a una BD de staging aparte con INGENIALAB_SQLITE_PATH.
            "NAME": os.environ.get("INGENIALAB_SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "progress:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# RNF-05: el token de sesión expira tras 30 minutos de inactividad.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True

# RNF-05: HTTPS obligatorio en producción.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ACT-211A2: los seis módulos (CU-01 a CU-05 y tablero) están habilitados por defecto. Para limitar
# una instalación, define p. ej. INGENIALAB_MODULES=interviews,classification,modeling
ALL_MODULES = ["interviews", "classification", "modeling", "inspection", "reports", "progress"]
INGENIALAB_MODULES = [m for m in os.environ.get("INGENIALAB_MODULES", ",".join(ALL_MODULES)).split(",") if m]

# SCI-05: integración PlantUML (SDS §3.2).
PLANTUML_JAR = os.environ.get("PLANTUML_JAR", str(BASE_DIR / "vendor" / "plantuml.jar"))
PLANTUML_JAVA = os.environ.get("PLANTUML_JAVA", "java")
PLANTUML_CACHE_DIR = Path(os.environ.get("PLANTUML_CACHE_DIR", BASE_DIR / "var" / "diagram_cache"))
# ACT-207B: presupuesto del subproceso (objetivo interactivo < 2 s).
PLANTUML_TIMEOUT = float(os.environ.get("PLANTUML_TIMEOUT", "1.8"))
PLANTUML_DOT = os.environ.get("PLANTUML_DOT", "dot")
# Solo demostraciones explicitas: nunca confundir respaldo con PlantUML real.
PLANTUML_ALLOW_FALLBACK = os.environ.get("PLANTUML_ALLOW_FALLBACK", "0") == "1"

# ACT-211A1: proveedor opcional compatible con Chat Completions, solo en backend.
INGENIALAB_AI_MODE = os.environ.get("INGENIALAB_AI_MODE", "catalog")
INGENIALAB_AI_ENDPOINT = os.environ.get("INGENIALAB_AI_ENDPOINT", "")
INGENIALAB_AI_MODEL = os.environ.get("INGENIALAB_AI_MODEL", "")
INGENIALAB_AI_API_KEY = os.environ.get("INGENIALAB_AI_API_KEY", "")
# El adaptador valida el rango y usa catálogo si la configuración no es válida.
try:
    INGENIALAB_AI_TIMEOUT = float(os.environ.get("INGENIALAB_AI_TIMEOUT", "1.2"))
except ValueError:
    INGENIALAB_AI_TIMEOUT = 0

# ACT-211C: los errores CSRF de API mantienen el contrato JSON.
CSRF_FAILURE_VIEW = "apps.accounts.views.csrf_failure"

# ACT-211C: reducir arranque HotSpot sin ampliar el presupuesto PlantUML.
PLANTUML_FAST_START = os.environ.get("PLANTUML_FAST_START", "1") == "1"
