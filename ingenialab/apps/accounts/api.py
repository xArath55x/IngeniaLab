"""Utilidades compartidas por los endpoints JSON."""
import json

from django.http import JsonResponse


def read_json(request):
    if hasattr(request, "ingenialab_json"):
        return request.ingenialab_json
    try:
        data = json.loads(request.body or b"{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def ok(**data):
    return JsonResponse({"ok": True, **data})


def fail(message, status=400, **data):
    return JsonResponse({"ok": False, "message": message, **data}, status=status)
