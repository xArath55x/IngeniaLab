"""GamificationService / ScoringEngine (SCI-07): puntos, niveles e insignias (RF-06, RF-07).

Los puntos se derivan siempre del estado guardado de cada práctica, por lo que
reclasificar o reintentar nunca duplica puntaje.
"""
from django.db.models import Max, Sum

from .models import UserBadge

USE_CASE_POINTS = 20

LEVELS = [
    (0, "Aprendiz de Requisitos"),
    (100, "Analista Junior"),
    (250, "Analista de Requisitos"),
    (450, "Ingeniero(a) de Requisitos"),
    (700, "Arquitecto(a) de Requisitos"),
]

BADGES = {
    "first_interview": ("🎤", "Primera entrevista", "Finalizaste tu primera entrevista con un cliente virtual."),
    "thorough": ("🧭", "Entrevistador exhaustivo", "Cubriste todos los temas clave de una entrevista."),
    "classifier": ("🏷️", "Clasificador preciso", "Clasificaste toda una bitácora con 80 % de precisión o más."),
    "modeler": ("📐", "Modelador UML", "Guardaste tu primer caso de uso con diagrama."),
    "auditor": ("🔍", "Ojo de auditor", "Encontraste todos los defectos de una inspección."),
    "no_hints": ("💡", "Sin ayuda", "Concluiste una inspección sin solicitar pistas."),
    "reporter": ("📄", "Documentador", "Exportaste tu primer reporte técnico en PDF."),
}


def total_points(user):
    attempts = user.attempts.aggregate(i=Sum("interview_score"), c=Sum("classification_score"))
    inspections = user.inspections.filter(concluded_at__isnull=False).aggregate(s=Sum("score"))
    # Lecciones de casos de uso: cuenta el mejor XP de cada caso de uso, así repetir no acumula puntos.
    lessons = user.lessons.filter(status="completed").values("reference").annotate(best=Max("xp"))
    return ((attempts["i"] or 0) + (attempts["c"] or 0) + (inspections["s"] or 0)
            + user.use_cases.count() * USE_CASE_POINTS + sum(row["best"] for row in lessons))


def level_for(points):
    idx = max(i for i, (threshold, _) in enumerate(LEVELS) if points >= threshold)
    current_min, name = LEVELS[idx]
    if idx + 1 < len(LEVELS):
        next_min = LEVELS[idx + 1][0]
        pct = round(100 * (points - current_min) / (next_min - current_min))
    else:
        next_min, pct = None, 100
    return {"number": idx + 1, "name": name, "next_at": next_min, "percent": pct}


def _earned_codes(user):
    from apps.interviews.models import StudentAttempt
    from apps.classification.services import available_requirements

    codes = set()
    finished = user.attempts.filter(status=StudentAttempt.CLASSIFYING)
    if finished.exists():
        codes.add("first_interview")
    for a in finished:
        if not a.premature_finish:
            codes.add("thorough")
        available = available_requirements(a).count()
        if available and a.classifications.count() == available and a.classification_precision >= 80:
            codes.add("classifier")
    if user.use_cases.exists():
        codes.add("modeler")
    for ins in user.inspections.filter(concluded_at__isnull=False).select_related("exercise"):
        if ins.findings.filter(is_correct=True).count() == ins.exercise.defect_count:
            codes.add("auditor")
        if ins.hints_used == 0:
            codes.add("no_hints")
    if user.reports.exists():
        codes.add("reporter")
    return codes


def evaluate_badges(user):
    """Otorga las insignias nuevas y devuelve su descripción para mostrarlas como toast."""
    owned = set(user.badges.values_list("code", flat=True))
    new = _earned_codes(user) - owned
    for code in new:
        UserBadge.objects.get_or_create(user=user, code=code)
    return [{"icon": BADGES[c][0], "name": BADGES[c][1]} for c in new]


def badge_list(user):
    owned = {b.code: b for b in user.badges.all()}
    return [
        {"code": code, "icon": icon, "name": name, "description": desc, "owned": code in owned,
         "awarded_at": owned[code].awarded_at if code in owned else None}
        for code, (icon, name, desc) in BADGES.items()
    ]
