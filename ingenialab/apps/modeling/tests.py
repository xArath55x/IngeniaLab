"""Pruebas de construcción ACT-207A."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from apps.interviews.models import ScenarioVersion, StudentAttempt
from .forms import UseCaseForm
from .models import UseCaseSpecification
from .validators import RULES
SPEC = {'name':'Registrar préstamo','system_name':'Biblioteca','primary_actors':['Bibliotecario'],'secondary_actors':[], 'preconditions':'El bibliotecario inició sesión.','main_flow':['El Bibliotecario captura la matrícula.','El sistema registra el préstamo.'],'alternate_flows':[],'postconditions':'El préstamo queda registrado.','relations':[],'attempt_id':''}
class StructuredFormTests(SimpleTestCase):
    def form(self, **changes): return UseCaseForm(data={**SPEC, **changes})
    def test_complete_and_numbered(self):
        f=self.form();self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.numbered_steps(),[{'number':i,'text':s} for i,s in enumerate(SPEC['main_flow'],1)])
    def test_unicode_whitespace_normalization(self):
        f=self.form(name='  Registrar\t pre\u0301stamo  ',primary_actors=[' Bibliotecario ']);self.assertTrue(f.is_valid(),f.errors)
        self.assertEqual(f.cleaned_data['name'],'Registrar préstamo');self.assertEqual(f.cleaned_data['primary_actors'],['Bibliotecario'])
    def test_required_fields(self):
        for field,value in [('name',' \n\t '),('preconditions','  '),('postconditions',''),('primary_actors',[]),('main_flow',[]),('main_flow',['Un paso'])]:
            with self.subTest(field=field,value=value):
                f=self.form(**{field:value});self.assertFalse(f.is_valid());self.assertIn(field,f.errors)
    def test_no_silent_blank_rows(self):
        f=self.form(main_flow=['Paso','  ','Otro']);self.assertFalse(f.is_valid());self.assertIn('elemento 2',str(f.errors).lower())
    def test_wrong_types(self):
        for field,value in [('name',42),('preconditions',True),('primary_actors','Actor'),('main_flow',{'1':'Paso'}),('relations',[None]),('secondary_actors',[3]),('attempt_id','no-es-uuid')]:
            with self.subTest(field=field):
                f=self.form(**{field:value});self.assertFalse(f.is_valid());self.assertIn(field,f.errors)
    def test_repeated_cross_role_actors(self):
        for changes,field in [({'primary_actors':['Bibliotecario',' BIBLIOTECARIO ']},'primary_actors'),({'secondary_actors':['bibliotecario']},'secondary_actors')]:
            f=self.form(**changes);self.assertFalse(f.is_valid());self.assertIn(field,f.errors)
    def test_limits(self):
        for field,value in [('name','x'*201),('system_name','x'*201),('preconditions','x'*4001),('postconditions','x'*4001),('main_flow',['x'*1001,'Paso']),('main_flow',['Paso']*51),('primary_actors',[str(i) for i in range(11)]),('primary_actors',['x'*121]),('alternate_flows',['x']*21),('relations',[{'type':'include','target':str(i)} for i in range(21)])]:
            with self.subTest(field=field):
                f=self.form(**{field:value});self.assertFalse(f.is_valid());self.assertIn(field,f.errors)
    def test_invalid_relations(self):
        for rows in [[{'type':'other','target':'Otra'}],[{'type':'include','target':''}],[{'type':'include','target':'registrar PRÉSTAMO'}],[{'type':'include','target':'Validar'},{'type':'extend','target':' validar '}]]:
            f=self.form(relations=rows);self.assertFalse(f.is_valid());self.assertIn('relations',f.errors)
    def test_controls(self):
        for field,value in [('name','Registrar\x00 préstamo'),('primary_actors',['Biblio\u200btecario'])]:
            f=self.form(**{field:value});self.assertFalse(f.is_valid());self.assertIn(field,f.errors)
    def test_optional_and_default_system(self):
        f=self.form(system_name='  ');self.assertTrue(f.is_valid());self.assertEqual(f.cleaned_data['system_name'],'Sistema')

@override_settings(INGENIALAB_MODULES=['interviews','modeling'],PLANTUML_ALLOW_FALLBACK=True,PLANTUML_JAR='/no/existe-prueba.jar')
class StructuredApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_ingenialab',verbosity=0)
        cls.user=get_user_model().objects.create_user('modelador',password='Prueba207A!Segura')
        cls.other=get_user_model().objects.create_user('otro-modelador',password='Prueba207A!Segura')
        cls.version=ScenarioVersion.objects.first()
        cls.attempt=StudentAttempt.objects.create(user=cls.user,version=cls.version,status=StudentAttempt.CLASSIFYING)
        cls.foreign=StudentAttempt.objects.create(user=cls.other,version=cls.version,status=StudentAttempt.CLASSIFYING)
    def setUp(self): self.client.force_login(self.user)
    def post(self,route='validar',data=None):
        return self.client.post('/modelado/api/'+route+'/',json.dumps(SPEC if data is None else data),content_type='application/json')
    @patch('apps.modeling.views.plantuml.render')
    def test_validate_without_render_or_writes(self,render):
        r=self.post();self.assertEqual(r.status_code,200,r.content);self.assertTrue(r.json()['ok']);self.assertEqual(r.json()['numbered_steps'][1]['number'],2)
        render.assert_not_called();self.assertEqual(UseCaseSpecification.objects.count(),0)
    def test_normalized_response(self):
        self.assertEqual(self.post(data={**SPEC,'name':' Registrar   préstamo '}).json()['spec']['name'],'Registrar préstamo')
    def test_completed_interview_on_all_endpoints(self):
        self.attempt.status=StudentAttempt.INTERVIEWING;self.attempt.save()
        for route in ['validar','generar','guardar']:self.assertEqual(self.post(route).status_code,409)
    def test_reference_owner_and_status(self):
        for value in [str(self.foreign.id),'00000000-0000-0000-0000-000000000000']:
            r=self.post(data={**SPEC,'attempt_id':value});self.assertEqual(r.status_code,400);self.assertIn('attempt_id',r.json()['errors'])
        self.attempt.status=StudentAttempt.INTERVIEWING;self.attempt.save()
        self.assertEqual(self.post(data={**SPEC,'attempt_id':str(self.attempt.id)}).status_code,400)
    @patch('apps.modeling.views.plantuml.render')
    def test_cannot_bypass_backend(self,render):
        for route in ['validar','generar','guardar']:
            r=self.post(route,{**SPEC,'main_flow':['Paso',' '],'relations':[{'type':'bad','target':'Otra'}]})
            self.assertEqual(r.status_code,400);self.assertIn('main_flow',r.json()['errors']);self.assertIn('relations',r.json()['errors'])
        render.assert_not_called();self.assertEqual(UseCaseSpecification.objects.count(),0)
    def test_invalid_json(self):
        for body in ['[1,2]','null','true','{incorrecto','"texto"']:
            self.assertEqual(self.client.post('/modelado/api/validar/',body,content_type='application/json').status_code,400)
    def test_auth_csrf_method(self):
        self.client.logout();self.assertEqual(self.post().status_code,401)
        c=Client(enforce_csrf_checks=True);c.force_login(self.user)
        self.assertEqual(c.post('/modelado/api/validar/',json.dumps(SPEC),content_type='application/json').status_code,403)
        self.client.force_login(self.user);self.assertEqual(self.client.get('/modelado/api/validar/').status_code,405)
    def test_editor_scripts_rules(self):
        r=self.client.get('/modelado/nuevo/');self.assertContains(r,'modeling-validation.js');self.assertContains(r,'modeling-editor.js');self.assertContains(r,'Validar plantilla');self.assertEqual(r.context['validation_rules'],RULES)
    def test_save_edit_owner(self):
        spec={**SPEC,'name':' Registrar   préstamo ','attempt_id':str(self.attempt.id)}
        self.assertEqual(self.post('generar',spec).status_code,200)
        r=self.post('guardar',spec);self.assertEqual(r.status_code,200,r.content)
        uc=UseCaseSpecification.objects.get();self.assertEqual(uc.name,'Registrar préstamo');self.assertEqual(uc.attempt,self.attempt);self.assertEqual(uc.main_flow,SPEC['main_flow']);self.assertTrue(uc.diagram.svg.startswith('<svg'))
        self.assertEqual(self.post('guardar',{**spec,'id':str(uc.id),'postconditions':'Estado actualizado.'}).status_code,200);self.assertEqual(UseCaseSpecification.objects.count(),1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/modelado/'+str(uc.id)+'/').status_code,404);self.assertEqual(self.post('guardar',{**SPEC,'id':str(uc.id)}).status_code,404)
    def test_bad_case_id(self):self.assertEqual(self.post('guardar',{**SPEC,'id':'incorrecto'}).status_code,400)

class SharedValidationCasesTests(SimpleTestCase):
    def test_shared_frontend_backend_contract(self):
        from pathlib import Path
        from django.conf import settings
        cases=json.loads((settings.BASE_DIR/'tests'/'modeling-cases.json').read_text())
        self.assertEqual(cases['rules'],RULES)
        for case in cases['cases']:
            with self.subTest(case=case['name']):
                form=UseCaseForm(data=case['data']);self.assertEqual(form.is_valid(),not bool(case['error']))
                if case['error']:self.assertIn(case['error'],form.errors)
                else:
                    self.assertEqual(form.cleaned_data['name'],'Registrar préstamo')
                    self.assertEqual([s['number'] for s in form.numbered_steps()],[1,2])
