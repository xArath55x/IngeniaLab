"""ACT-207B: adaptador, cache, errores, sintaxis y motor real opcional."""
import io,os,subprocess,tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from PIL import Image
from django.test import SimpleTestCase,override_settings
from . import service
from .builder import build_usecase_diagram
SVG=b'<svg xmlns="http://www.w3.org/2000/svg"><text>Bibliotecario</text></svg>'
SPEC={'name':'Registrar préstamo','system_name':'Biblioteca','primary_actors':['Bibliotecario'],'secondary_actors':['Correo'],'relations':[{'type':'include','target':'Verificar'},{'type':'extend','target':'Notificar'}]}
CODE=build_usecase_diagram(SPEC)
def png():
    out=io.BytesIO();Image.new('RGB',(10,10),'white').save(out,format='PNG');return out.getvalue()
class BuilderTests(SimpleTestCase):
    def test_structure_and_directions(self):
        self.assertTrue(CODE.startswith('@startuml\n'));self.assertTrue(CODE.endswith('@enduml'))
        self.assertIn('actor "Bibliotecario" as P1',CODE);self.assertIn('UC0 ..> UC1 : <<include>>',CODE);self.assertIn('UC2 ..> UC0 : <<extend>>',CODE);self.assertNotIn('smetana',CODE)
    def test_escaped_labels(self):
        hostile='Estudiante"\n@enduml\n!include /etc/passwd\n[[https://example.com]]<script>'
        code=build_usecase_diagram({**SPEC,'primary_actors':[hostile]})
        self.assertEqual(code.count('\n@enduml'),1);self.assertNotIn('\n!include',code);self.assertNotIn('[[',code);self.assertNotIn('<script>',code)
    def test_deterministic_hash(self):
        self.assertEqual(build_usecase_diagram(SPEC),CODE)
        self.assertNotEqual(service.code_hash(CODE),service.code_hash(build_usecase_diagram({**SPEC,'name':'Otro'})))

@override_settings(PLANTUML_ALLOW_FALLBACK=False,PLANTUML_JAR='/no/existe-unit.jar',PLANTUML_TIMEOUT=1.8)
class AdapterTests(SimpleTestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.cache=Path(tmp.name)
        config=override_settings(PLANTUML_CACHE_DIR=tmp.name);config.enable();self.addCleanup(config.disable)
    @patch('integrations.plantuml.service._execute',return_value=SVG)
    def test_svg_cache_and_no_second_subprocess(self,execute):
        a=service.render(CODE);b=service.render(CODE);self.assertFalse(a.cached);self.assertTrue(b.cached);self.assertEqual(a.data,b.data);self.assertEqual(execute.call_count,1)
        self.assertEqual(service._cache_path(CODE,'svg').stem,service.code_hash(CODE))
    @patch('integrations.plantuml.service._execute')
    def test_png_and_svg_separate_cache(self,execute):
        image=png();execute.side_effect=[SVG,image]
        a=service.render(CODE,'png');svg=service.render(CODE,'svg');b=service.render(CODE,'png');self.assertEqual(a.data,image);self.assertTrue(b.cached);self.assertEqual(svg.data,SVG);self.assertEqual(execute.call_count,2)
    @patch('integrations.plantuml.service._execute',return_value=SVG)
    def test_corrupt_cache_replaced_atomically(self,execute):
        path=service._cache_path(CODE,'svg');path.parent.mkdir(parents=True);path.write_bytes(b'broken')
        self.assertFalse(service.render(CODE).cached);self.assertEqual(path.read_bytes(),SVG);self.assertEqual(list(path.parent.glob('.render-*')),[])
    @patch('integrations.plantuml.service._execute',return_value=SVG)
    def test_code_and_engine_change_invalidate(self,execute):
        service.render(CODE);service.render(CODE.replace('Registrar','Consultar'))
        with override_settings(PLANTUML_DOT='other-dot'):self.assertFalse(service.render(CODE).cached)
        self.assertEqual(execute.call_count,3)
    def test_missing_jar_fails_without_fake_success(self):
        with self.assertRaises(service.PlantUMLError) as e:service.render(CODE)
        self.assertEqual(e.exception.code,'jar_missing');self.assertEqual(list(self.cache.rglob('*.svg')),[])
    def test_explicit_fallback_is_not_cached(self):
        with override_settings(PLANTUML_ALLOW_FALLBACK=True):
            r=service.render(CODE);self.assertEqual(r.engine,'fallback');self.assertFalse(r.cached);self.assertTrue(r.warning)
        self.assertEqual(list(self.cache.rglob('*.svg')),[])
    def test_bad_input_format_and_images(self):
        for code,format in [(CODE,'pdf'),('hello','svg')]:
            with self.assertRaises(service.PlantUMLError):service.render(code,format)
        with self.assertRaises(service.PlantUMLError):service._valid_image(b'\x89PNG\r\n\x1a\nerror','png')
    def test_svg_errors_scripts_and_external_resources_rejected(self):
        for body in ['<text>An error has occurred</text>','<script>alert(1)</script>','<image href="https://example.com"/>','<g onload="alert(1)"/>']:
            with self.subTest(body=body),self.assertRaises(service.PlantUMLError):service._valid_image(('<svg xmlns="http://www.w3.org/2000/svg">'+body+'</svg>').encode(),'svg')
    @patch('integrations.plantuml.service._write_atomic',side_effect=PermissionError)
    @patch('integrations.plantuml.service._execute',return_value=SVG)
    def test_unwritable_cache_returns_image_with_warning(self,execute,write):
        r=service.render(CODE);self.assertEqual(r.data,SVG);self.assertTrue(r.warning)
    def test_missing_java_graphviz_and_timeout(self):
        with tempfile.NamedTemporaryFile(suffix='.jar') as jar,override_settings(PLANTUML_JAR=jar.name):
            with patch('integrations.plantuml.service.shutil.which',return_value=None),self.assertRaises(service.PlantUMLError) as e:service.render(CODE)
            self.assertEqual(e.exception.code,'java_missing')
            with patch('integrations.plantuml.service.shutil.which',side_effect=['java',None]),self.assertRaises(service.PlantUMLError) as e:service.render(CODE)
            self.assertEqual(e.exception.code,'graphviz_missing')
            with patch('integrations.plantuml.service.shutil.which',return_value='/tool'),patch('integrations.plantuml.service.subprocess.run',side_effect=subprocess.TimeoutExpired('java',1.8)),self.assertRaises(service.PlantUMLError) as e:service.render(CODE)
            self.assertEqual(e.exception.status,504)
    def test_process_error_not_cached(self):
        with tempfile.NamedTemporaryFile(suffix='.jar') as jar,override_settings(PLANTUML_JAR=jar.name),patch('integrations.plantuml.service.shutil.which',return_value='/tool'),patch('integrations.plantuml.service.subprocess.run',return_value=subprocess.CompletedProcess([],1,SVG,b'syntax error')):
            with self.assertRaises(service.PlantUMLError):service.render(CODE)
        self.assertEqual(list(self.cache.rglob('*.svg')),[])

@skipUnless(os.environ.get('INGENIALAB_TEST_PLANTUML')=='1','Activa INGENIALAB_TEST_PLANTUML=1 con Java, Graphviz y JAR instalados.')
@override_settings(PLANTUML_ALLOW_FALLBACK=False)
class RealEngineTests(SimpleTestCase):
    def test_real_svg_png_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp,override_settings(PLANTUML_CACHE_DIR=tmp):
            svg=service.render(CODE);self.assertIn('Bibliotecario',svg.svg);self.assertEqual(svg.engine,'plantuml');self.assertFalse(svg.cached)
            self.assertIn('include',svg.svg);self.assertIn('extend',svg.svg)
            image=service.render(CODE,'png');self.assertTrue(image.data.startswith(b'\x89PNG'));self.assertEqual(service.render(CODE,'png').data,image.data);self.assertTrue(service.render(CODE).cached)
    def test_cold_png_within_interactive_target(self):
        with tempfile.TemporaryDirectory() as tmp,override_settings(PLANTUML_CACHE_DIR=tmp):
            image=service.render(CODE,'png');self.assertEqual(image.engine,'plantuml');self.assertLess(image.duration_ms,2000)

@override_settings(PLANTUML_ALLOW_FALLBACK=False,PLANTUML_TIMEOUT=1.8)
class Act209AdapterContractTests(SimpleTestCase):
    def test_invalid_format_types_have_controlled_error(self):
        for value in [[],{},None,False,1,'pdf']:
            with self.subTest(format=value):
                with self.assertRaises(service.PlantUMLError) as exc:service.render(CODE,value)
                self.assertEqual(exc.exception.code,'invalid_format')
    def test_subprocess_arguments_and_output(self):
        with tempfile.NamedTemporaryFile(suffix='.jar') as jar,override_settings(PLANTUML_JAR=jar.name),patch('integrations.plantuml.service.shutil.which',return_value='/tool'),patch('integrations.plantuml.service.subprocess.run',return_value=subprocess.CompletedProcess([],0,SVG,b'')) as run:
            self.assertEqual(service._execute(CODE,'svg',1.5),SVG)
            args,kwargs=run.call_args
            self.assertIn('-pipe',args[0]);self.assertIn('-tsvg',args[0]);self.assertIn(jar.name,args[0]);self.assertEqual(kwargs['input'],CODE.encode());self.assertEqual(kwargs['timeout'],1.5);self.assertFalse(kwargs.get('shell',False));self.assertEqual(kwargs['env']['GRAPHVIZ_DOT'],'/tool')
    def test_os_error_and_stderr_crash_image_are_not_success(self):
        with tempfile.NamedTemporaryFile(suffix='.jar') as jar,override_settings(PLANTUML_JAR=jar.name),patch('integrations.plantuml.service.shutil.which',return_value='/tool'):
            for outcome,expected in [(OSError('No Java'),'execution_failed'),(subprocess.CompletedProcess([],0,SVG,b'java.lang.IllegalStateException'),'render_failed')]:
                with self.subTest(expected=expected),patch('integrations.plantuml.service.subprocess.run',side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome),self.assertRaises(service.PlantUMLError) as exc:service._execute(CODE,'svg',1.8)
                self.assertEqual(exc.exception.code,expected)
    def test_atomic_write_cleans_temp_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory,patch('integrations.plantuml.service.os.replace',side_effect=OSError('disco')):
            with self.assertRaises(OSError):service._write_atomic(Path(directory)/'test.svg',SVG)
            self.assertEqual(list(Path(directory).iterdir()),[])
    def test_corrupt_png_is_regenerated_after_svg_certification(self):
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory),patch('integrations.plantuml.service._execute',side_effect=[SVG,png()]) as execute:
            path=service._cache_path(CODE,'png');path.parent.mkdir(parents=True);path.write_bytes(b'broken')
            result=service.render(CODE,'png');self.assertFalse(result.cached);self.assertEqual(execute.call_count,2);self.assertTrue(service.render(CODE,'png').cached)
    def test_png_is_not_a_fallback_format(self):
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory,PLANTUML_ALLOW_FALLBACK=True,PLANTUML_JAR='/no/existe'),self.assertRaises(service.PlantUMLError):service.render(CODE,'png')

    def test_exhausted_budget_does_not_run_subprocess(self):
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory,PLANTUML_TIMEOUT=0),patch('integrations.plantuml.service._execute') as execute:
            with self.assertRaises(service.PlantUMLError) as exc:service.render(CODE)
            self.assertEqual(exc.exception.code,'timeout');execute.assert_not_called()

@skipUnless(os.environ.get('INGENIALAB_TEST_PLANTUML')=='1','Requiere motor Java/Graphviz real.')
@override_settings(PLANTUML_ALLOW_FALLBACK=False)
class Act209RealSyntaxTests(SimpleTestCase):
    def test_invalid_uml_rejected_and_not_cached(self):
        code='@startuml\nthis is not UML ???\n@enduml'
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory):
            for format in ('svg','png'):
                with self.subTest(format=format),self.assertRaises(service.PlantUMLError):service.render(code,format)
            self.assertEqual(list(Path(directory).rglob('*.svg')),[]);self.assertEqual(list(Path(directory).rglob('*.png')),[])
    def test_quoted_unicode_labels_and_relations_render(self):
        code=build_usecase_diagram({**SPEC,'name':'Registrar préstamo "especial"','primary_actors':['Estudiante José'],'secondary_actors':['Servicio externo']})
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory):
            result=service.render(code);self.assertEqual(result.engine,'plantuml')
            import xml.etree.ElementTree as ET
            text=' '.join(ET.fromstring(result.data).itertext())
            self.assertIn('Estudiante José',text);self.assertIn('include',text);self.assertIn('extend',text)

    def test_graphviz_error_cannot_be_reported_as_png_success(self):
        bad_dot=__import__('shutil').which('false')
        if not bad_dot:self.skipTest('Este ensayo usa el ejecutable false de Linux para simular un dot averiado.')
        with tempfile.TemporaryDirectory() as directory,override_settings(PLANTUML_CACHE_DIR=directory,PLANTUML_DOT=bad_dot):
            with self.assertRaises(service.PlantUMLError):service.render(CODE,'png')
            self.assertEqual(list(Path(directory).rglob('*.png')),[])
