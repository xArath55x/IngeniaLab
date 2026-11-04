"""ACT-207B: errores HTTP, formatos, permisos y recorrido real opcional."""
import base64,json,os,tempfile
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase,override_settings
from apps.interviews.models import ScenarioVersion,StudentAttempt
from .models import UseCaseSpecification,GeneratedDiagram
from .tests import SPEC
from integrations.plantuml import service

@override_settings(INGENIALAB_MODULES=['interviews','modeling'],PLANTUML_ALLOW_FALLBACK=False)
class DiagramApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user('uml-user')
        cls.other=get_user_model().objects.create_user('uml-other')
        version=ScenarioVersion.objects.create(scenario_code='UML-TEST',version_number='1',title='Biblioteca')
        StudentAttempt.objects.create(user=cls.user,version=version,status=StudentAttempt.CLASSIFYING)
        cls.uc=UseCaseSpecification.objects.create(user=cls.user,name='Prueba',system_name='Sistema',actors={'primary':['Usuario'],'secondary':[]},preconditions='Ninguna',main_flow=['Uno','Dos'],postconditions='Registrado',plantuml_code='@startuml\nactor Usuario\n@enduml')
    def setUp(self):self.client.force_login(self.user)
    def post(self,route,data):return self.client.post('/modelado/api/'+route+'/',json.dumps(data),content_type='application/json')
    @patch('apps.modeling.views.plantuml.render',side_effect=service.PlantUMLError('Instala el JAR','jar_missing'))
    def test_error_details_and_no_partial_save(self,render):
        for route in ['generar','guardar']:
            response=self.post(route,SPEC);self.assertEqual(response.status_code,503);self.assertEqual(response.json()['error'],'jar_missing');self.assertIn('JAR',response.json()['message'])
        self.assertEqual(UseCaseSpecification.objects.count(),1);self.assertEqual(GeneratedDiagram.objects.count(),0)
    @patch('apps.modeling.views.plantuml.render',side_effect=service.PlantUMLError('Tiempo agotado','timeout',504))
    def test_timeout_status(self,render):self.assertEqual(self.post('generar',SPEC).status_code,504)
    def test_invalid_format(self):self.assertEqual(self.post('generar',{**SPEC,'format':'pdf'}).status_code,400)
    @patch('apps.modeling.views.plantuml.render')
    def test_download_content_and_owner(self,render):
        render.return_value=service.RenderResult('', 'a'*64,'plantuml',True,b'PNG','png',0.5)
        path=f'/modelado/{self.uc.id}/diagrama/png/'
        response=self.client.get(path);self.assertEqual(response.content,b'PNG');self.assertEqual(response['Content-Type'],'image/png');self.assertEqual(response['X-Diagram-Cache'],'HIT')
        self.client.force_login(self.other);self.assertEqual(self.client.get(path).status_code,404);self.assertEqual(render.call_count,1)
        self.client.logout();self.assertEqual(self.client.get(path).status_code,302)
    @skipUnless(os.environ.get('INGENIALAB_TEST_PLANTUML')=='1','Motor real opcional: INGENIALAB_TEST_PLANTUML=1')
    def test_full_real_png_preview_save_download(self):
        with tempfile.TemporaryDirectory() as cache,override_settings(PLANTUML_CACHE_DIR=cache):
            result=self.post('generar',{**SPEC,'format':'png'});self.assertEqual(result.status_code,200,result.content)
            body=result.json();self.assertEqual(body['engine'],'plantuml');self.assertEqual(body['image_format'],'png');self.assertTrue(base64.b64decode(body['png_data_uri'].split(',')[1]).startswith(b'\x89PNG'))
            self.assertIn('<svg',body['svg']);self.assertLess(body['duration_ms'],2000)
            saved=self.post('guardar',SPEC);self.assertEqual(saved.status_code,200,saved.content);uid=saved.json()['id']
            self.assertEqual(GeneratedDiagram.objects.get(use_case_id=uid).engine,'plantuml')
            for format in ('svg','png'):
                response=self.client.get(f'/modelado/{uid}/diagrama/{format}/');self.assertEqual(response.status_code,200,response.content);self.assertEqual(response['X-Diagram-Cache'],'HIT')
