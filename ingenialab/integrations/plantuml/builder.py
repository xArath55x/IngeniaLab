"""Transformación de la especificación estructurada a código PlantUML (RF-05)."""


def _q(text):
    # PlantUML interpreta markup dentro de etiquetas: codificar metacaracteres
    # conserva el texto visible sin aceptar enlaces, saltos ni directivas.
    clean = " ".join(str(text).split())
    return "".join(c if c.isalnum() or c in " .,_-/()" else f"<U+{ord(c):04X}>" for c in clean)


def build_usecase_diagram(spec: dict) -> str:
    lines = ["@startuml", "left to right direction", "skinparam shadowing false",
             "skinparam usecase {", "  BackgroundColor #E6F2F1", "  BorderColor #006A68", "}",
             "skinparam actorBorderColor #006A68", "skinparam rectangleBorderColor #5B7083", ""]
    for i, a in enumerate(spec["primary_actors"], 1):
        lines.append(f'actor "{_q(a)}" as P{i}')
    for i, a in enumerate(spec["secondary_actors"], 1):
        lines.append(f'actor "{_q(a)}" as S{i}')
    lines.append(f'rectangle "{_q(spec["system_name"])}" {{')
    lines.append(f'  usecase "{_q(spec["name"])}" as UC0')
    for i, r in enumerate(spec["relations"], 1):
        lines.append(f'  usecase "{_q(r["target"])}" as UC{i}')
    lines.append("}")
    for i, _ in enumerate(spec["primary_actors"], 1):
        lines.append(f"P{i} --> UC0")
    for i, _ in enumerate(spec["secondary_actors"], 1):
        lines.append(f"UC0 --> S{i}")
    for i, r in enumerate(spec["relations"], 1):
        if r["type"] == "include":
            lines.append(f"UC0 ..> UC{i} : <<include>>")
        else:
            lines.append(f"UC{i} ..> UC0 : <<extend>>")
    lines.append("@enduml")
    return "\n".join(lines)
