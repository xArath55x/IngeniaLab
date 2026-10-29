"""Prueba end-to-end sobre una base de datos de staging (ACT-214C, WP.14).

Crea una BD SQLite limpia en var/staging/, aplica migraciones, carga el contenido con
seed_ingenialab, levanta runserver y recorre por HTTP los cinco casos de uso como lo haría
el navegador: CU-01 entrevista, CU-03 clasificación, CU-02 modelado, CU-04 inspección y
CU-05 reporte PDF, más el tablero, el aislamiento entre cuentas y la sesión (RF-12).

No toca db.sqlite3 ni una base PostgreSQL configurada. Uso, desde ingenialab/:

    .venv/bin/python scripts/e2e_staging.py
    .venv/bin/python scripts/e2e_staging.py --allow-plantuml-fallback   # equipo sin Java/Graphviz

Sale con código 0 si todos los pasos pasan. Deja la evidencia en var/staging/:
e2e_report.json, reporte_e2e.pdf y server.log.
"""
import argparse
from datetime import datetime
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "var" / "staging"
MODULES = "interviews,classification,modeling,inspection,reports,progress"
PASSWORD = "StagingE2e#2026"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
USE_CASE = {
    "name": "Registrar préstamo", "system_name": "Biblioteca",
    "primary_actors": ["Bibliotecario"], "secondary_actors": ["Servicio de correo"],
    "preconditions": "El bibliotecario inició sesión.",
    "main_flow": ["El Bibliotecario captura la matrícula.", "El sistema registra el préstamo."],
    "alternate_flows": ["FA-1: El alumno tiene 3 préstamos; el sistema rechaza."],
    "postconditions": "El préstamo queda registrado.",
    "relations": [{"type": "include", "target": "Verificar límite de préstamos"}],
}


class StepFailed(Exception):
    pass


def check(condition, message):
    if not condition:
        raise StepFailed(message)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    """Cliente HTTP con cookies y CSRF, equivalente a una pestaña del navegador."""

    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        cookies = urllib.request.HTTPCookieProcessor(self.jar)
        self.follow = urllib.request.build_opener(cookies)
        self.stay = urllib.request.build_opener(cookies, _NoRedirect)

    def csrf(self):
        return next((c.value for c in self.jar if c.name == "csrftoken"), "")

    def request(self, method, path, body=None, headers=None, follow=True):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            resp = (self.follow if follow else self.stay).open(req, timeout=30)
        except urllib.error.HTTPError as e:
            resp = e
        content = resp.read()
        return {"status": resp.status if hasattr(resp, "status") else resp.code,
                "path": urllib.parse.urlparse(resp.geturl()).path,
                "headers": resp.headers, "body": content,
                "text": content.decode("utf-8", "replace")}

    def get(self, path, follow=True):
        return self.request("GET", path, follow=follow)

    def form(self, path, data):
        data = {"csrfmiddlewaretoken": self.csrf(), **data}
        return self.request("POST", path, urllib.parse.urlencode(data).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded", "Referer": self.base + path})

    def api(self, path, data=None):
        r = self.request("POST", path, json.dumps(data or {}).encode(),
                         {"Content-Type": "application/json", "X-CSRFToken": self.csrf()})
        try:
            r["json"] = json.loads(r["text"])
        except ValueError:
            r["json"] = {}
        return r


def json_script(html, element_id):
    m = re.search(rf'<script id="{element_id}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def signup(browser, username, name):
    browser.get("/cuentas/registro/")
    r = browser.form("/cuentas/registro/", {
        "username": username, "first_name": name, "email": f"{username}@staging.uaz.edu.mx",
        "password1": PASSWORD, "password2": PASSWORD,
    })
    check(r["status"] == 200 and r["path"] == "/", f"registro de {username}: terminó en {r['path']} ({r['status']})")


class Flow:
    """Pasos del recorrido; cada uno lanza StepFailed con el motivo si algo no coincide."""

    def __init__(self, base, allow_fallback):
        self.base = base
        self.allow_fallback = allow_fallback
        self.alumno = Browser(base)
        self.ctx = {}

    def cu01_entrevista(self):
        signup(self.alumno, "e2e-alumno", "Alumna Staging")
        r = self.alumno.get("/elicitacion/")
        starts = re.findall(rf'action="(/elicitacion/iniciar/{UUID}/)"', r["text"])
        check(starts, "no hay escenarios activos tras seed_ingenialab")
        r = self.alumno.form(starts[0], {})
        m = re.fullmatch(rf"/elicitacion/intento/({UUID})/", r["path"])
        check(m, f"iniciar entrevista terminó en {r['path']}")
        attempt = m.group(1)
        asked, finished = 0, False
        while not finished:
            options = json_script(self.alumno.get(f"/elicitacion/intento/{attempt}/")["text"], "options-data")
            check(options, f"sin opciones después de {asked} preguntas y sin finalizar")
            r = self.alumno.api(f"/elicitacion/api/intento/{attempt}/preguntar/", {"question_id": options[0]["id"]})
            check(r["status"] == 200 and r["json"].get("ok"), f"preguntar: {r['status']} {r['text'][:200]}")
            check(r["json"]["entry"]["segments"], "la respuesta del cliente no trae segmentos de bitácora")
            asked += 1
            finished = r["json"]["finished"]
            check(asked <= 9, "la entrevista excede MAX_QUESTIONS (9)")
        self.ctx["attempt"] = attempt
        return f"{asked} preguntas formuladas; entrevista finalizada"

    def cu03_clasificacion(self):
        attempt = self.ctx["attempt"]
        r = self.alumno.get(f"/clasificacion/intento/{attempt}/")
        check(r["status"] == 200, f"vista de clasificación respondió {r['status']}")
        reqs = list(dict.fromkeys(re.findall(rf'data-req="({UUID})"', r["text"])))
        check(reqs, "la bitácora no tiene declaraciones resaltables")
        url = f"/clasificacion/api/intento/{attempt}/clasificar/"
        reclassified = 0
        for req in reqs:
            r = self.alumno.api(url, {"requirement_id": req, "category": "RF"})
            check(r["json"].get("ok") and r["json"].get("explanation"), f"clasificar: {r['text'][:200]}")
            if not r["json"]["is_correct"]:
                r = self.alumno.api(url, {"requirement_id": req, "category": "RNF"})
                check(r["json"].get("is_correct") and r["json"].get("reclassified"), f"reclasificar: {r['text'][:200]}")
                reclassified += 1
        check(len(r["json"]["rows"]) == len(reqs), "la reclasificación duplicó filas")
        check(r["json"]["precision"] == 100.0, f"precisión final {r['json']['precision']} %")
        r = self.alumno.api(url, {"requirement_id": reqs[0], "category": "AMBOS"})
        check(r["status"] == 400, "se aceptó una categoría distinta de RF/RNF")
        return f"{len(reqs)} declaraciones, {reclassified} reclasificadas sin duplicar; precisión 100 %"

    def cu02_modelado(self):
        r = self.alumno.api("/modelado/api/guardar/", {**USE_CASE, "attempt_id": self.ctx["attempt"]})
        check(r["status"] == 200 and r["json"].get("ok"), f"guardar caso de uso: {r['status']} {r['text'][:200]}")
        engine = r["json"]["engine"]
        check(engine == "plantuml" or self.allow_fallback,
              f"se usó el motor '{engine}'; el respaldo no cuenta como integración real (usa --allow-plantuml-fallback)")
        check("<svg" in r["json"]["svg"], "el diagrama no es SVG")
        self.ctx["use_case"] = r["json"]["id"]
        return f"caso de uso guardado; diagrama con motor '{engine}'"

    def cu04_inspeccion(self):
        r = self.alumno.get("/inspeccion/")
        starts = re.findall(rf'action="(/inspeccion/iniciar/{UUID}/)"', r["text"])
        check(starts, "no hay ejercicios de inspección activos")
        r = self.alumno.form(starts[0], {})
        m = re.fullmatch(rf"/inspeccion/intento/({UUID})/", r["path"])
        check(m, f"iniciar inspección terminó en {r['path']}")
        attempt = m.group(1)
        fragments = list(dict.fromkeys(re.findall(rf'data-id="({UUID})"', r["text"])))
        check(fragments, "el ejercicio no tiene fragmentos")
        base = f"/inspeccion/api/intento/{attempt}/"
        r = self.alumno.api(base + "hallazgo/", {"fragment_id": fragments[0], "defect_type": "ambiguity"})
        check(r["json"].get("ok") and r["json"].get("status"), f"hallazgo: {r['text'][:200]}")
        r = self.alumno.api(base + "pista/")
        check(r["json"].get("ok") and r["json"].get("hint"), f"pista: {r['text'][:200]}")
        r = self.alumno.api(base + "concluir/")
        check(r["json"].get("ok"), f"concluir: {r['text'][:200]}")
        summary = r["json"]["summary"]
        r = self.alumno.api(base + "hallazgo/", {"fragment_id": fragments[0], "defect_type": "ambiguity"})
        check(r["status"] == 400, "se aceptó un hallazgo en una inspección concluida")
        self.ctx["inspection"] = attempt
        return f"{len(fragments)} fragmentos; concluida con precisión {summary['precision']} % y {summary['score']} pts"

    def tablero(self):
        r = self.alumno.get("/")
        m = re.search(r"(\d+) puntos acumulados", r["text"])
        check(r["status"] == 200 and m, "el tablero no muestra los puntos acumulados")
        points = int(m.group(1))
        check(points > 0, "el tablero muestra 0 puntos tras completar las actividades")
        for href in ("/elicitacion/", "/modelado/", "/inspeccion/", "/reportes/"):
            check(f'href="{href}"' in r["text"], f"la navegación no enlaza {href}")
        return f"{points} puntos; navegación con los seis módulos"

    def cu05_reporte(self):
        r = self.alumno.get("/reportes/")
        check(r["status"] == 200, f"resumen de reportes respondió {r['status']}")
        r = self.alumno.get("/reportes/descargar/")
        check(r["headers"].get("Content-Type") == "application/pdf", f"tipo {r['headers'].get('Content-Type')}")
        check(r["body"].startswith(b"%PDF"), "el archivo descargado no es PDF")
        (STAGING / "reporte_e2e.pdf").write_bytes(r["body"])
        return f"PDF de {len(r['body']) // 1024} KB guardado en var/staging/reporte_e2e.pdf"

    def aislamiento(self):
        otro = Browser(self.base)
        signup(otro, "e2e-otro", "Otro Staging")
        own = {
            f"/elicitacion/intento/{self.ctx['attempt']}/": "la entrevista",
            f"/clasificacion/intento/{self.ctx['attempt']}/": "la clasificación",
            f"/modelado/{self.ctx['use_case']}/": "el caso de uso",
            f"/inspeccion/intento/{self.ctx['inspection']}/": "la inspección",
        }
        for path, label in own.items():
            # 404, o redirección por una precondición (p. ej. CU-02 exige una entrevista propia terminada).
            r = otro.get(path)
            check(r["status"] == 404 or (r["path"] != path and USE_CASE["name"] not in r["text"]),
                  f"otra cuenta pudo abrir {label} ajena")
        r = otro.api(f"/inspeccion/api/intento/{self.ctx['inspection']}/pista/")
        check(r["status"] == 404, "otra cuenta pudo operar la API de una inspección ajena")
        check("0 puntos acumulados" in otro.get("/")["text"], "el tablero de otra cuenta no inicia en 0 puntos")
        r = otro.get("/reportes/descargar/")
        check("No hay actividades guardadas" in r["text"], "otra cuenta generó un reporte sin actividades propias")
        return "4 vistas ajenas bloqueadas (404 o redirección), API ajena → 404; tablero y reporte sin datos ajenos"

    def sesion(self):
        anon = Browser(self.base)
        r = anon.get("/", follow=False)
        check(r["status"] == 302 and "/cuentas/login/" in r["headers"].get("Location", ""), "el tablero no exige sesión")
        anon.get("/cuentas/login/")
        r = anon.api(f"/inspeccion/api/intento/{uuid.uuid4()}/pista/")
        check(r["status"] == 401 and r["json"].get("error") == "session_expired", f"API sin sesión: {r['status']}")
        self.alumno.form("/cuentas/logout/", {})
        r = self.alumno.api(f"/clasificacion/api/intento/{self.ctx['attempt']}/pista/")
        check(r["status"] == 401, f"API después de cerrar sesión respondió {r['status']}")
        return "sin sesión: tablero → login y /api/ → 401 JSON (RF-12)"


def run(cmd, env, log=None):
    result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        raise SystemExit(f"Falló: {' '.join(cmd[1:])}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--allow-plantuml-fallback", action="store_true",
                        help="acepta el respaldo SVG si no hay Java/Graphviz (no vale como integración real)")
    args = parser.parse_args()
    # En Windows la consola suele ser cp1252 y no tiene caracteres como «→»: se sustituyen en vez de abortar.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")

    STAGING.mkdir(parents=True, exist_ok=True)
    db = STAGING / "staging.sqlite3"
    for f in (db, db.with_name(db.name + "-journal")):
        f.unlink(missing_ok=True)
    # Sin caché previa, para que CU-02 pase por el motor PlantUML en cada corrida.
    shutil.rmtree(STAGING / "diagram_cache", ignore_errors=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")}
    env.update({
        "INGENIALAB_SQLITE_PATH": str(db), "INGENIALAB_MODULES": MODULES, "INGENIALAB_DEBUG": "1",
        "INGENIALAB_AI_MODE": "catalog", "PLANTUML_CACHE_DIR": str(STAGING / "diagram_cache"),
        "PLANTUML_ALLOW_FALLBACK": "1" if args.allow_plantuml_fallback else "0",
        # Los subprocesos escriben UTF-8 sin importar la codificación del sistema.
        "PYTHONIOENCODING": "utf-8",
    })
    python = sys.executable
    run([python, "manage.py", "migrate", "--noinput"], env)
    seed = run([python, "manage.py", "seed_ingenialab"], env).strip().splitlines()

    base = f"http://127.0.0.1:{args.port}"
    log = open(STAGING / "server.log", "w", encoding="utf-8")
    server = subprocess.Popen([python, "manage.py", "runserver", f"127.0.0.1:{args.port}", "--noreload"],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    steps = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/cuentas/login/", timeout=1)
                break
            except OSError:
                if server.poll() is not None:
                    raise SystemExit("runserver terminó al arrancar; revisa var/staging/server.log")
                time.sleep(0.5)
        else:
            raise SystemExit("runserver no respondió en 30 s; revisa var/staging/server.log")

        flow = Flow(base, args.allow_plantuml_fallback)
        plan = [
            ("CU-01 Entrevista", flow.cu01_entrevista),
            ("CU-03 Clasificación RF/RNF", flow.cu03_clasificacion),
            ("CU-02 Modelado y diagrama", flow.cu02_modelado),
            ("CU-04 Inspección", flow.cu04_inspeccion),
            ("Tablero de progreso", flow.tablero),
            ("CU-05 Reporte PDF", flow.cu05_reporte),
            ("Aislamiento entre cuentas", flow.aislamiento),
            ("Sesión y API (RF-12)", flow.sesion),
        ]
        for name, fn in plan:
            start = time.perf_counter()
            try:
                detail, ok = fn(), True
            except StepFailed as e:
                detail, ok = str(e), False
            ms = round((time.perf_counter() - start) * 1000)
            steps.append({"paso": name, "ok": ok, "detalle": detail, "ms": ms})
            print(f"{'PASA' if ok else 'FALLA'}  {name:<30} {ms:>6} ms  {detail}")
            if not ok:
                break
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    passed = len(steps) == len(plan) and all(s["ok"] for s in steps)
    report = {
        "actividad": "ACT-214C", "fecha": datetime.now().isoformat(timespec="seconds"), "commit": commit,
        "python": sys.version.split()[0], "bd": str(db.relative_to(ROOT)), "modulos": MODULES.split(","),
        "seed": seed, "plantuml_fallback_permitido": args.allow_plantuml_fallback,
        "resultado": "PASA" if passed else "FALLA", "pasos": steps,
    }
    (STAGING / "e2e_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'PASA' if passed else 'FALLA'}: {sum(s['ok'] for s in steps)}/{len(plan)} pasos · "
          f"evidencia en var/staging/e2e_report.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
