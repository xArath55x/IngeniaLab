"""Vista simplificada heredada, solo con habilitacion explicita; no es PlantUML."""
import re
import html

_ACTOR = re.compile(r'^actor "(.+)" as (\w+)$')
_UC = re.compile(r'^usecase "(.+)" as (\w+)$')
_SYS = re.compile(r'^rectangle "(.+)" \{$')
_LINK = re.compile(r"^(\w+) (-->|\.\.>) (\w+)(?: : <<(\w+)>>)?$")


def render_fallback(code: str) -> str:
    """Renderizador de respaldo para el subconjunto de PlantUML que genera builder.py."""
    actors, usecases, links, system = {}, {}, [], "Sistema"
    for raw in code.splitlines():
        line = raw.strip()
        if m := _ACTOR.match(line):
            actors[m[2]] = m[1]
        elif m := _UC.match(line):
            usecases[m[2]] = m[1]
        elif m := _SYS.match(line):
            system = m[1]
        elif m := _LINK.match(line):
            links.append((m[1], m[2], m[3], m[4]))

    left = [k for k in actors if k.startswith("P")]
    right = [k for k in actors if k.startswith("S")]
    ucs = list(usecases)
    rows = max(len(left), len(right), len(ucs), 1)
    row_h, width = 110, 760
    height = rows * row_h + 60
    pos = {}

    def column(keys, x):
        offset = (rows - len(keys)) * row_h / 2
        for i, k in enumerate(keys):
            pos[k] = (x, 50 + offset + i * row_h + row_h / 2)

    column(left, 80)
    column(ucs, 380)
    column(right, 680)
    e = html.escape
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif" font-size="13">',
             '<defs><marker id="arr" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
             '<path d="M0,0 L10,4 L0,8 z" fill="#33475b"/></marker></defs>',
             f'<rect x="200" y="20" width="360" height="{height - 40}" rx="6" fill="none" stroke="#5B7083"/>',
             f'<text x="380" y="40" text-anchor="middle" font-weight="bold">{e(system)}</text>']
    for a, kind, b, stereo in links:
        if a not in pos or b not in pos:
            continue
        (x1, y1), (x2, y2) = pos[a], pos[b]
        x1 += 30 if a in actors else 110
        x2 -= 30 if b in actors else 110
        dash = ' stroke-dasharray="6,4"' if kind == "..>" else ""
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#33475b"{dash} marker-end="url(#arr)"/>')
        if stereo:
            parts.append(f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 6}" text-anchor="middle" '
                         f'font-size="11">«{e(stereo)}»</text>')
    for k, name in actors.items():
        x, y = pos[k]
        parts.append(f'<g stroke="#006A68" stroke-width="2" fill="none"><circle cx="{x}" cy="{y - 30}" r="10"/>'
                     f'<line x1="{x}" y1="{y - 20}" x2="{x}" y2="{y + 5}"/><line x1="{x - 15}" y1="{y - 12}" x2="{x + 15}" y2="{y - 12}"/>'
                     f'<line x1="{x}" y1="{y + 5}" x2="{x - 12}" y2="{y + 22}"/><line x1="{x}" y1="{y + 5}" x2="{x + 12}" y2="{y + 22}"/></g>'
                     f'<text x="{x}" y="{y + 40}" text-anchor="middle">{e(name)}</text>')
    for k, name in usecases.items():
        x, y = pos[k]
        parts.append(f'<ellipse cx="{x}" cy="{y}" rx="110" ry="30" fill="#E6F2F1" stroke="#006A68"/>'
                     f'<text x="{x}" y="{y + 4}" text-anchor="middle">{e(name[:34])}</text>')
    parts.append("</svg>")
    return "".join(parts)
