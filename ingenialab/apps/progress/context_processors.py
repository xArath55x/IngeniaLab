from django.conf import settings

from apps.accounts.models import is_teacher

from . import partidas
from .services import level_for, total_points


def progress_summary(request):
    ctx = {"modules": settings.INGENIALAB_MODULES}
    if is_teacher(getattr(request, "user", None)):
        ctx["is_teacher"] = True
        return ctx
    if "progress" in ctx["modules"] and getattr(request, "user", None) and request.user.is_authenticated:
        points = total_points(request.user)
        ctx.update(nav_points=points, nav_level=level_for(points))
    if getattr(request, "user", None) and request.user.is_authenticated:
        match = getattr(request, "resolver_match", None)
        # Barra de la partida en las pantallas de cada etapa (en el tablero ya está la tarjeta completa).
        if match and match.app_name in ("interviews", "classification", "modeling", "inspection"):
            current = partidas.active(request.user)
            if current:
                ctx["partida_bar"] = partidas.state(current)
    return ctx
