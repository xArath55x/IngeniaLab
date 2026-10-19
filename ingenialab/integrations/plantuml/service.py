"""ACT-207B: PlantUML local real, Graphviz, SVG/PNG y cache atomica SHA-256."""
import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from PIL import Image
from django.conf import settings

log = logging.getLogger(__name__)
FORMATS = {"svg": "image/svg+xml", "png": "image/png"}
CACHE_VERSION = "plantuml-v2-graphviz"
ERROR_MARKERS = ("an error has occurred", "has crashed", "cannot parse result", "syntax error?", "error java.lang", "dot executable does not exist")

class PlantUMLError(Exception):
    def __init__(self, message, code="render_failed", status=503):
        super().__init__(message); self.code = code; self.status = status

@dataclass
class RenderResult:
    svg: str
    code_hash: str
    engine: str
    cached: bool
    data: bytes = b""
    format: str = "svg"
    duration_ms: float = 0
    warning: str = ""
    @property
    def content_type(self): return FORMATS[self.format]

def code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()

def _cache_path(code, format):
    # La clave de contenido sigue siendo SHA-256 del codigo; un espacio de
    # nombres adicional invalida caches de versiones/configuraciones previas.
    jar = Path(settings.PLANTUML_JAR)
    try:
        stat = jar.stat(); identity = f"{jar.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError: identity = str(jar)
    identity += str(settings.PLANTUML_JAVA) + str(getattr(settings, "PLANTUML_DOT", "dot"))
    engine = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return Path(settings.PLANTUML_CACHE_DIR) / CACHE_VERSION / engine / f"{code_hash(code)}.{format}"

def _valid_image(data, format):
    if not data or len(data) > 8_000_000:
        raise PlantUMLError("El generador devolvio una imagen vacia o demasiado grande.", "invalid_image")
    if format == "png":
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.width * image.height > 16_000_000: raise ValueError()
                image.verify()
        except Exception as e:
            raise PlantUMLError("PlantUML no devolvio un PNG valido.", "invalid_image") from e
        return data
    try:
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper(): raise ValueError()
        root = ET.fromstring(data)
        if root.tag != "{http://www.w3.org/2000/svg}svg": raise ValueError()
        visible = " ".join(n.text or "" for n in root.iter() if n.tag.endswith("}text")).lower()
        if any(marker in visible for marker in ERROR_MARKERS): raise ValueError()
        for node in root.iter():
            tag = node.tag.rsplit("}", 1)[-1].lower()
            if tag in ("script", "foreignobject", "image", "iframe", "a", "style", "animate", "set"): raise ValueError()
            for attr, value in node.attrib.items():
                attr = attr.rsplit("}", 1)[-1].lower()
                if attr.startswith("on"): raise ValueError()
                if attr in ("href", "src") and not value.startswith("#"): raise ValueError()
                if "url(" in value.lower() and not re.fullmatch(r"url\(#[A-Za-z0-9_-]+\)", value): raise ValueError()
    except (ET.ParseError, ValueError) as e:
        raise PlantUMLError("PlantUML devolvio un SVG invalido o una imagen de error. Ejecuta plantuml_check.", "invalid_image") from e
    return data

def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".render-", delete=False) as f:
            name = f.name; f.write(data)
        os.replace(name, path)
    finally:
        if name:
            try: os.unlink(name)
            except FileNotFoundError: pass

def _execute(code, format, timeout):
    jar = Path(settings.PLANTUML_JAR)
    if not jar.is_file(): raise PlantUMLError("Falta plantuml.jar. Ejecuta python manage.py install_plantuml.", "jar_missing")
    java = shutil.which(settings.PLANTUML_JAVA)
    dot = shutil.which(getattr(settings, "PLANTUML_DOT", "dot"))
    if not java: raise PlantUMLError("Falta Java en PATH. Instala Java 17 o configura PLANTUML_JAVA.", "java_missing")
    if not dot: raise PlantUMLError("Falta Graphviz. Instala Graphviz y agrega dot al PATH.", "graphviz_missing")
    env = os.environ.copy(); env["GRAPHVIZ_DOT"] = dot
    command = [java, "-Djava.awt.headless=true", "-DPLANTUML_SECURITY_PROFILE=SECURE", "-Xmx256m",
               "-jar", str(jar), "-pipe", "-t" + format, "-charset", "UTF-8", "-noerror"]
    try:
        result = subprocess.run(command, input=code.encode("utf-8"), capture_output=True,
                                timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired as e:
        raise PlantUMLError("PlantUML excedio el tiempo disponible. Reduce el diagrama o revisa plantuml_check.", "timeout", 504) from e
    except OSError as e:
        raise PlantUMLError("No se pudo ejecutar Java. Revisa PLANTUML_JAVA.", "execution_failed") from e
    stderr = result.stderr.decode("utf-8", "replace").lower()
    if result.returncode or any(marker in stderr for marker in ("exception", "error line", "cannot parse result", "syntax error")):
        log.warning("PlantUML fallo: codigo=%s, detalle=%s", result.returncode, stderr[:500])
        raise PlantUMLError("PlantUML no pudo generar el diagrama. Ejecuta plantuml_check.", "render_failed")
    return _valid_image(result.stdout, format)

def render(plantuml_code, format="svg"):
    start = time.perf_counter()
    if format not in FORMATS: raise PlantUMLError("Formato permitido: svg o png.", "invalid_format", 400)
    if not isinstance(plantuml_code, str) or not plantuml_code.startswith("@startuml\n") or not plantuml_code.rstrip().endswith("@enduml") or len(plantuml_code.encode()) > 100_000:
        raise PlantUMLError("Codigo UML invalido o demasiado grande.", "invalid_code", 400)
    digest = code_hash(plantuml_code)
    path = _cache_path(plantuml_code, format)
    cached = False; warning = ""
    try:
        data = _valid_image(path.read_bytes(), format); cached = True
    except (OSError, PlantUMLError): data = None
    if data is None:
        try:
            budget = float(settings.PLANTUML_TIMEOUT)
            if format == "png":
                # Verificar el SVG evita aceptar un PNG que solo contiene un
                # mensaje de error. El editor genera primero SVG y lo reutiliza.
                certified = render(plantuml_code, "svg")
                if certified.engine != "plantuml": raise PlantUMLError("PNG requiere el motor PlantUML real.")
            remaining = budget - (time.perf_counter() - start)
            if remaining <= 0: raise PlantUMLError("Se agoto el tiempo de generacion.", "timeout", 504)
            data = _execute(plantuml_code, format, remaining)
        except PlantUMLError as e:
            if not getattr(settings, "PLANTUML_ALLOW_FALLBACK", False) or format != "svg": raise
            from .fallback import render_fallback
            svg = render_fallback(plantuml_code)
            return RenderResult(svg, digest, "fallback", False, svg.encode(), format,
                                round((time.perf_counter()-start)*1000, 3), str(e))
        try: _write_atomic(path, data)
        except OSError:
            warning = "Diagrama generado; no se pudo escribir la cache. Revisa los permisos de var/."
            log.warning(warning)
    return RenderResult(data.decode("utf-8") if format == "svg" else "", digest, "plantuml", cached,
                        data, format, round((time.perf_counter()-start)*1000, 3), warning)
