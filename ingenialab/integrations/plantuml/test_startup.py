"""ACT-211C: opciones de arranque y presupuesto original del subproceso."""
import subprocess
import tempfile
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from . import service


class StartupBudgetTests(SimpleTestCase):
    def test_fast_start_es_conmutable_y_no_amplia_timeout(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
        with tempfile.NamedTemporaryFile(suffix='.jar') as jar:
            for enabled in (True,False):
                with self.subTest(enabled=enabled), override_settings(PLANTUML_JAR=jar.name,PLANTUML_FAST_START=enabled), patch('integrations.plantuml.service.shutil.which',return_value='/tool'), patch('integrations.plantuml.service.subprocess.run',return_value=subprocess.CompletedProcess([],0,svg,b'')) as run:
                    service._execute('@startuml\n@enduml','svg',1.8)
                    self.assertEqual('-XX:TieredStopAtLevel=1' in run.call_args.args[0],enabled)
                    self.assertEqual('-XX:+UseSerialGC' in run.call_args.args[0],enabled)
                    self.assertEqual(run.call_args.kwargs['timeout'],1.8)

    def test_png_informa_certificacion_y_tiempo_total_sin_ocultarlos(self):
        from .tests import png
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
        clock=(x/1000 for x in range(100))
        with tempfile.TemporaryDirectory() as cache, override_settings(PLANTUML_CACHE_DIR=cache,PLANTUML_TIMEOUT=1.8), patch('integrations.plantuml.service._execute',side_effect=[svg,png()]), patch('integrations.plantuml.service.time.perf_counter',side_effect=lambda:next(clock)):
            result=service.render('@startuml\nactor Alumno\n@enduml','png')
        self.assertGreater(result.certification_ms,0)
        self.assertGreater(result.total_duration_ms,result.duration_ms)
        self.assertAlmostEqual(result.total_duration_ms,result.duration_ms+result.certification_ms,places=3)

    def _render_with(self, side_effect):
        with tempfile.TemporaryDirectory() as cache, override_settings(PLANTUML_CACHE_DIR=cache,PLANTUML_TIMEOUT=1.8,PLANTUML_ALLOW_FALLBACK=False), patch('integrations.plantuml.service._execute',side_effect=side_effect) as execute:
            try:
                return service.render('@startuml\nactor Alumno\n@enduml','svg'),execute
            except service.PlantUMLError as error:
                return error,execute

    def test_h03_tiempo_agotado_se_reintenta_una_vez_con_el_mismo_presupuesto(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
        result,execute=self._render_with([service.PlantUMLError('lento','timeout',504),svg])
        self.assertEqual(result.engine,'plantuml')
        self.assertEqual(execute.call_count,2)
        self.assertEqual(execute.call_args.args[2],1.8)

    def test_h03_segundo_tiempo_agotado_devuelve_504(self):
        error,execute=self._render_with([service.PlantUMLError('lento','timeout',504),service.PlantUMLError('lento','timeout',504)])
        self.assertEqual((error.code,error.status),('timeout',504))
        self.assertEqual(execute.call_count,2)

    def test_h03_otros_errores_no_se_reintentan(self):
        error,execute=self._render_with([service.PlantUMLError('falta jar','jar_missing')])
        self.assertEqual(error.code,'jar_missing')
        self.assertEqual(execute.call_count,1)
