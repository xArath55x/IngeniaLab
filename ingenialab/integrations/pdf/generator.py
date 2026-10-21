"""PDFReportGenerator (SCI-08): reporte técnico de práctica (RF-08 / CU-05).

Nota de diseño: el SDS contempla WeasyPrint; para el MVP se usa ReportLab porque no requiere
bibliotecas del sistema (Pango/Cairo) y funciona igual en macOS, Windows y Linux. La interfaz
pública (`build_report`) es la misma, por lo que el motor puede cambiarse sin tocar las vistas.
"""
import io
import logging

from django.utils import timezone
from reportlab.graphics import renderPDF  # noqa: F401  (registro de renderers)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from svglib.svglib import svg2rlg

log = logging.getLogger(__name__)

ACCENT = colors.HexColor("#006a68")
LIGHT = colors.HexColor("#e6f2f1")
GRID = colors.HexColor("#c9d6dc")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("H1x", parent=s["Heading1"], textColor=ACCENT, fontSize=18, spaceAfter=6))
    s.add(ParagraphStyle("H2x", parent=s["Heading2"], textColor=ACCENT, fontSize=14, spaceBefore=10))
    s.add(ParagraphStyle("H3x", parent=s["Heading3"], fontSize=11.5, spaceBefore=6))
    s.add(ParagraphStyle("Cell", parent=s["BodyText"], fontSize=9, leading=11))
    s.add(ParagraphStyle("Small", parent=s["BodyText"], fontSize=8.5, textColor=colors.HexColor("#5b7083")))
    s.add(ParagraphStyle("Center", parent=s["BodyText"], alignment=TA_CENTER))
    return s


def _esc(text):
    return (str(text) or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(rows, widths, st, header=True):
    data = [[c if isinstance(c, Paragraph) else Paragraph(_esc(c), st["Cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _svg_flowable(svg_text, max_width):
    try:
        drawing = svg2rlg(io.BytesIO(svg_text.encode("utf-8")))
    except Exception as e:  # svglib puede fallar con SVG exóticos; el reporte no debe romperse
        log.warning("No se pudo convertir el diagrama a PDF: %s", e)
        return None
    if drawing is None or not drawing.width:
        return None
    scale = min(1.0, max_width / drawing.width, (12 * cm) / drawing.height)
    drawing.width, drawing.height = drawing.width * scale, drawing.height * scale
    drawing.scale(scale, scale)
    return drawing


def build_report(*, report_id, user, level, points, attempts, use_cases, inspections):
    buf = io.BytesIO()
    st = _styles()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"IngeniaLab — Reporte {report_id}", author=user.get_full_name() or user.username)
    width = doc.width
    story = [
        Paragraph("IngeniaLab — Reporte Técnico de Práctica", st["H1x"]),
        Paragraph("Universidad Autónoma de Zacatecas · Introducción a la Ingeniería de Software", st["Small"]),
        Spacer(1, 8),
        _table([
            ["Estudiante", user.get_full_name() or user.username],
            ["Usuario", user.username],
            ["Reporte", report_id],
            ["Fecha de emisión", timezone.localtime().strftime("%d/%m/%Y %H:%M")],
            ["Nivel formativo", f"{level['number']} · {level['name']} ({points} puntos)"],
        ], [4.5 * cm, width - 4.5 * cm], st, header=False),
        Spacer(1, 4),
        Paragraph("Documento formativo generado automáticamente. No constituye una calificación oficial.", st["Small"]),
    ]

    if attempts:
        story.append(Paragraph("1. Elicitación y clasificación de requisitos", st["H2x"]))
        for a in attempts:
            block = [Paragraph(f"{_esc(a['title'])} — {a['code']}", st["H3x"]),
                     Paragraph(f"Cobertura: {a['coverage']} · Puntaje entrevista: {a['interview_score']} · "
                               f"Precisión de clasificación: {a['precision']} % · Pistas: {a['hints']}", st["Small"]),
                     Spacer(1, 4)]
            if a.get("log"):
                block.append(Paragraph("Bitácora de la entrevista", st["H3x"]))
                log_rows = [["#", "Pregunta formulada", "Respuesta del cliente", "Pts"]]
                log_rows += [[str(i), e["question"], e["answer"], str(e["points"])]
                             for i, e in enumerate(a["log"], 1)]
                block.append(_table(log_rows, [0.8 * cm, 5.5 * cm, width - 7.8 * cm, 1.5 * cm], st))
                block.append(Spacer(1, 6))
            if a["rows"]:
                rows = [["#", "Declaración", "Clasificación", "Resultado"]]
                rows += [[str(i), r["statement"], r["category"], "Correcto" if r["is_correct"] else "Inconsistente"]
                         for i, r in enumerate(a["rows"], 1)]
                block.append(_table(rows, [0.8 * cm, width - 6.3 * cm, 2.5 * cm, 3 * cm], st))
            else:
                block.append(Paragraph("Sin requisitos clasificados.", st["Small"]))
            story += block

    if use_cases:
        story.append(PageBreak())
        story.append(Paragraph("2. Especificaciones de casos de uso", st["H2x"]))
        for uc in use_cases:
            rows = [
                ["Campo", "Contenido"],
                ["Nombre", uc.name],
                ["Sistema", uc.system_name],
                ["Actores principales", ", ".join(uc.actors.get("primary", []))],
                ["Actores secundarios", ", ".join(uc.actors.get("secondary", [])) or "—"],
                ["Precondiciones", uc.preconditions],
                ["Flujo principal", "<br/>".join(f"{i}. {_esc(s)}" for i, s in enumerate(uc.main_flow, 1))],
                ["Flujos alternos / excepciones", "<br/>".join(_esc(s) for s in uc.alternate_flows) or "—"],
                ["Postcondiciones", uc.postconditions],
                ["Relaciones", ", ".join(f"«{r['type']}» {r['target']}" for r in uc.relations) or "—"],
            ]
            rows = [[r[0], Paragraph(r[1] if r[0] in ("Flujo principal", "Flujos alternos / excepciones")
                                     else _esc(r[1]), st["Cell"])] for r in rows]
            story.append(Paragraph(_esc(uc.name), st["H3x"]))
            story.append(_table(rows, [4.5 * cm, width - 4.5 * cm], st))
            diagram = getattr(uc, "diagram", None)
            flow = _svg_flowable(diagram.svg, width) if diagram else None
            if flow:
                story.append(Spacer(1, 6))
                story.append(KeepTogether([Paragraph("Diagrama UML generado", st["Small"]), flow]))
            story.append(Spacer(1, 10))

    if inspections:
        story.append(Paragraph("3. Inspección de defectos", st["H2x"]))
        rows = [["Ejercicio", "Defectos hallados", "Precisión", "Pistas", "Puntaje"]]
        rows += [[i["title"], f"{i['found']} / {i['total']}", f"{i['precision']} %", str(i["hints"]), str(i["score"])]
                 for i in inspections]
        story.append(_table(rows, [width - 10.5 * cm, 3 * cm, 2.5 * cm, 2 * cm, 3 * cm], st))

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5b7083"))
        canvas.drawString(2 * cm, 1.2 * cm, f"IngeniaLab · Byte Force · {report_id}")
        canvas.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f"Página {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
