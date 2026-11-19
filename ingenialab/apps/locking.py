"""Bloqueo de un intento dentro de una transacción (ACT-313B; OBS-05 de la Matriz de Compatibilidad)."""


def lock_and_refresh(instance):
    """Bloquea la fila y relee sus campos propios en una sola consulta.

    La vista carga el intento antes de abrir la transacción; sin esto, dos peticiones simultáneas parten
    del mismo contador y una se pierde. En PostgreSQL bloquea la fila; en SQLite la transacción ya tiene el
    bloqueo de escritura (BEGIN IMMEDIATE). Solo relee los campos que no son relaciones, para no tirar las
    relaciones que la vista ya cargó (exercise, version, user).
    """
    model = type(instance)
    fields = [f.attname for f in model._meta.concrete_fields if not f.is_relation and not f.primary_key]
    instance.refresh_from_db(fields=fields, from_queryset=model.objects.select_for_update())
