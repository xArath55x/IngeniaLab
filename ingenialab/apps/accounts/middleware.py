"""SessionGuard (SCI-01): las peticiones a /api/ sin sesión activa reciben 401 JSON.

Así el cliente JS puede conservar el estado en pantalla y pedir reautenticación (RF-12)
en lugar de recibir una redirección HTML.
"""
import json
from django.core.exceptions import RequestDataTooBig
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect


class ApiSessionGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "/api/" in request.path and not request.user.is_authenticated:
            return JsonResponse(
                {"ok": False, "error": "session_expired",
                 "message": "Tu sesión expiró. Inicia sesión nuevamente; tu trabajo guardado se conserva."},
                status=401,
            )
        expected = request.headers.get("X-IngeniaLab-User")
        if "/api/" in request.path and expected and expected != str(request.user.pk):
            return JsonResponse({"ok": False, "error": "session_changed",
                                 "message": "La cuenta activa cambió. Tu borrador se conserva; vuelve a tu cuenta antes de enviarlo."}, status=409)
        return self.get_response(request)


# Prefijo de URL → módulo que lo atiende. "/" exacto es el tablero (módulo progress).
MODULE_PREFIXES = [
    ("/clasificacion/", "classification"),
    ("/modelado/", "modeling"),
    ("/inspeccion/", "inspection"),
    ("/reportes/", "reports"),
]


class ModuleGateMiddleware:
    """Bloquea los módulos deshabilitados en settings.INGENIALAB_MODULES y redirige a la entrevista."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        enabled = settings.INGENIALAB_MODULES
        path = request.path
        module = "progress" if path == "/" else next((m for p, m in MODULE_PREFIXES if path.startswith(p)), None)
        if module and module not in enabled:
            if "/api/" in path:
                return JsonResponse({"ok": False, "message": "Este módulo no está disponible."}, status=404)
            return redirect("interviews:scenarios")
        return self.get_response(request)


class ApiRequestGuardMiddleware:
    """ACT-211C: sólo objetos JSON y tamaño acotado antes de ejecutar servicios."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "/api/" in request.path and request.method in ("POST", "PUT", "PATCH"):
            try:
                raw = request.body
                if len(raw) > 160000:
                    raise RequestDataTooBig()
                data = json.loads(raw or b"{}")
                if not isinstance(data, dict):
                    raise ValueError()
            except RequestDataTooBig:
                return JsonResponse({"ok": False, "error": "payload_too_large", "message": "La solicitud excede el tamaño permitido."}, status=413)
            except (ValueError, UnicodeDecodeError):
                return JsonResponse({"ok": False, "error": "invalid_json", "message": "Envía un objeto JSON válido."}, status=400)
            request.ingenialab_json = data
        return self.get_response(request)
