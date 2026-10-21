"""Pruebas del exportador de reporte PDF (CU-05 / RF-08) — ACT-208D."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from reportlab import rl_config

from apps.progress import tests as base
from apps.progress.views import _report_data
from integrations.pdf.generator import build_report

SVG_VALIDO = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
              '<rect width="200" height="100" fill="#cccccc"/></svg>')
NIVEL = {"number": 1, "name": "Aprendiz"}


def _usuario():
    return SimpleNamespace(username="alumno", get_full_name=lambda: "Ana Alumna")


def _intento(**cambios):
    datos = {
        "title": "Escenario de prueba", "code": "ESC-T-01", "coverage": "2/9 preguntas",
        "interview_score": 15, "precision": 50.0, "hints": 1, "classified": 1, "available": 2,
        "rows": [{"statement": "REQ_CLASIFICADO_XYZ", "category": "RF", "is_correct": True}],
        "log": [
            {"question": "PREGUNTA_UNO_ABC", "answer": "RESPUESTA_UNO_ABC", "points": 10},
            {"question": "PREGUNTA_DOS_ABC", "answer": "RESPUESTA_DOS_ABC", "points": 5},
        ],
    }
    datos.update(cambios)
    return datos


def _caso_de_uso(svg=None):
    return SimpleNamespace(
        name="CU_PRESTAR_LIBRO", system_name="Biblioteca",
        actors={"primary": ["Alumno"], "secondary": []}, preconditions="Sesion activa",
        main_flow=["Paso uno", "Paso dos"], alternate_flows=["FA-1 Libro no disponible"],
        postconditions="Prestamo registrado", relations=[{"type": "include", "target": "Autenticar"}],
        diagram=SimpleNamespace(svg=svg) if svg is not None else None,
    )


def _inspeccion():
    return {"title": "INSPECCION_EJ_ABC", "found": 3, "total": 5, "precision": 75.0, "hints": 1, "score": 22}


class GeneradorPdfTests(SimpleTestCase):
    def setUp(self):
        # Sin compresión, el texto ASCII del PDF se puede buscar en los bytes.
        parche = mock.patch.object(rl_config, "pageCompression", 0)
        parche.start()
        self.addCleanup(parche.stop)

    def pdf(self, attempts=None, use_cases=None, inspections=None):
        return build_report(report_id="ALUMNO-ABC123", user=_usuario(), level=NIVEL, points=40,
                            attempts=[_intento()] if attempts is None else attempts,
                            use_cases=use_cases or [], inspections=inspections or [])

    def test_pdf_valido_con_las_tres_secciones(self):
        data = self.pdf(use_cases=[_caso_de_uso()], inspections=[_inspeccion()])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"%%EOF", data[-32:])
        for marcador in (b"REQ_CLASIFICADO_XYZ", b"CU_PRESTAR_LIBRO", b"INSPECCION_EJ_ABC", b"ALUMNO-ABC123"):
            self.assertIn(marcador, data)

    def test_la_bitacora_incluye_preguntas_respuestas_y_puntos(self):
        data = self.pdf()
        for marcador in (b"PREGUNTA_UNO_ABC", b"RESPUESTA_UNO_ABC", b"PREGUNTA_DOS_ABC", b"RESPUESTA_DOS_ABC"):
            self.assertIn(marcador, data)

    def test_sin_bitacora_el_reporte_se_genera_igual(self):
        data = self.pdf(attempts=[_intento(log=[])])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertNotIn(b"PREGUNTA_UNO_ABC", data)
        self.assertIn(b"REQ_CLASIFICADO_XYZ", data)

    def test_diagrama_uml_valido_se_incrusta(self):
        data = self.pdf(use_cases=[_caso_de_uso(SVG_VALIDO)])
        self.assertIn(b"Diagrama UML generado", data)

    def test_caso_de_uso_sin_diagrama_no_rompe(self):
        data = self.pdf(use_cases=[_caso_de_uso(None)])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"CU_PRESTAR_LIBRO", data)
        self.assertNotIn(b"Diagrama UML generado", data)

    def test_svg_invalido_se_omite_sin_romper_el_reporte(self):
        data = self.pdf(use_cases=[_caso_de_uso("esto no es un svg")])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"CU_PRESTAR_LIBRO", data)
        self.assertNotIn(b"Diagrama UML generado", data)

    def test_caracteres_especiales_no_rompen_el_pdf(self):
        raro = "Cada <alumno> & su <b>tutor</i> & otros"
        data = self.pdf(attempts=[_intento(
            rows=[{"statement": raro, "category": "RF", "is_correct": False}],
            log=[{"question": raro, "answer": raro, "points": 0}])])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"tutor", data)
        # La etiqueta </i> se imprime como texto (fragmento "/i"); no se interpreta como formato.
        self.assertIn(b"(/i)", data)

    def test_reporte_solo_con_inspecciones(self):
        data = self.pdf(attempts=[], inspections=[_inspeccion()])
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn(b"INSPECCION_EJ_ABC", data)


@base.ALL_MODULES
class BitacoraEnReporteTests(base.BaseCase):
    def test_report_data_incluye_la_bitacora_en_orden_y_con_puntos(self):
        attempt = self.finished_attempt()
        attempts, _, _ = _report_data(self.user)
        reporte = next(a for a in attempts if a["code"] == attempt.version.scenario_code)
        self.assertEqual(len(reporte["log"]), 9)
        self.assertTrue(all({"question", "answer", "points"} <= set(e) for e in reporte["log"]))
        self.assertTrue(all(e["question"] and e["answer"] for e in reporte["log"]))
        self.assertEqual(sum(e["points"] for e in reporte["log"]), attempt.interview_score)

    def test_descarga_con_bitacora_sigue_devolviendo_pdf(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/",
                  {"requirement_id": str(req.id), "category": "RF"})
        r = self.client.get("/reportes/descargar/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
