"""ACT-211C: regresiones de JSON, sesión, reintentos y timeout controlado."""
import json
import uuid
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from apps.interviews.models import ScenarioVersion, StudentAttempt
from apps.modeling.models import UseCaseSpecification
from apps.modeling.tests import SPEC
from integrations.plantuml.service import RenderResult, PlantUMLError

SVG='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><text x="1" y="20">Prueba</text></svg>'


@override_settings(INGENIALAB_MODULES=['interviews','classification','modeling'],INGENIALAB_AI_MODE='catalog')
class IntegrationResilienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_ingenialab',stdout=StringIO())
        cls.user=get_user_model().objects.create_user('resiliencia',password='Prueba211C!')
        cls.other=get_user_model().objects.create_user('otro-resiliencia',password='Prueba211C!')
        cls.version=ScenarioVersion.objects.get(scenario_code='ESC-BIBLIOTECA-01')

    def setUp(self):
        self.client.force_login(self.user)
        self.attempt=StudentAttempt.objects.create(user=self.user,version=self.version)

    def post(self,url,body,**headers):
        return self.client.post(url,json.dumps(body),content_type='application/json',**headers)

    def test_json_no_objeto_no_causa_500_ni_escrituras(self):
        url=reverse('interviews:api_ask',args=[self.attempt.id])
        for value in [[],None,'texto',5,True]:
            with self.subTest(value=value):
                response=self.post(url,value)
                self.assertEqual(response.status_code,400)
                self.assertFalse(response.json()['ok'])
        self.assertEqual(self.attempt.log_entries.count(),0)

    def test_json_roto_utf8_invalido_y_exceso_se_controlan(self):
        url=reverse('interviews:api_reset',args=[self.attempt.id])
        for raw in [b'{',b'\xff']:
            with self.subTest(raw=raw):
                self.assertEqual(self.client.post(url,raw,content_type='application/json').status_code,400)
        raw=json.dumps({'texto':'x'*160001})
        self.assertEqual(self.client.post(url,raw,content_type='application/json').status_code,413)

    def test_identidad_de_pestana_anterior_no_escribe_en_nueva_cuenta(self):
        self.client.force_login(self.other)
        attempt=StudentAttempt.objects.create(user=self.other,version=self.version)
        question=self.version.questions.get(round_number=1,quality='high')
        r=self.post(reverse('interviews:api_ask',args=[attempt.id]),{'question_id':str(question.id)},HTTP_X_INGENIALAB_USER=str(self.user.pk))
        self.assertEqual(r.status_code,409);self.assertEqual(attempt.log_entries.count(),0)

    def test_sesion_expirada_tiene_prioridad_sobre_json_invalido(self):
        self.client.logout()
        r=self.client.post(reverse('interviews:api_ask',args=[self.attempt.id]),b'[',content_type='application/json')
        self.assertEqual(r.status_code,401)

    def test_metadata_sesion_renueva_csrf_y_no_se_cachea(self):
        r=self.client.get('/cuentas/api/sesion/')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['user_id'],str(self.user.pk))
        self.assertTrue(r.json()['csrf_token']);self.assertIn('no-store',r['Cache-Control'])

    def test_token_anterior_a_login_se_recupera_sin_desactivar_csrf(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.user)
        session=browser.get('/cuentas/api/sesion/')
        self.assertEqual(session.status_code,200)
        old_token=session.json()['csrf_token']
        from django.middleware.csrf import _get_new_csrf_string
        browser.cookies['csrftoken']=_get_new_csrf_string()
        url=reverse('interviews:api_reset',args=[self.attempt.id])
        r=browser.post(url,'{}',content_type='application/json',HTTP_X_CSRFTOKEN=old_token)
        self.assertEqual(r.status_code,403)
        refreshed=browser.get('/cuentas/api/sesion/').json()['csrf_token']
        r=browser.post(url,'{}',content_type='application/json',HTTP_X_CSRFTOKEN=refreshed)
        self.assertEqual(r.status_code,200)

    def test_reintento_pregunta_reproduce_bitacora_sin_reconsultar_ia(self):
        question=self.version.questions.get(round_number=1,quality='high')
        url=reverse('interviews:api_ask',args=[self.attempt.id]);body={'question_id':str(question.id)}
        with patch('apps.interviews.services.dialogue_answer', wraps=__import__('integrations.ai.dialogue',fromlist=['answer']).answer) as provider:
            first=self.post(url,body);again=self.post(url,body)
        self.assertEqual(first.status_code,200);self.assertEqual(again.status_code,200)
        self.assertEqual(first.json()['entry'],again.json()['entry'])
        self.assertEqual(provider.call_count,1);self.assertEqual(self.attempt.log_entries.count(),1)

    def test_formato_no_hashable_devuelve_400(self):
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        for value in [[],{},None]:
            with self.subTest(value=value):
                r=self.post(reverse('modeling:api_generate'),{**SPEC,'format':value})
                self.assertEqual(r.status_code,400)

    @patch('apps.modeling.views.plantuml.render',side_effect=PlantUMLError('Tiempo agotado','timeout',504))
    def test_timeout_modelado_no_guarda_datos_parciales(self,render):
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        r=self.post(reverse('modeling:api_save'),SPEC)
        self.assertEqual(r.status_code,504);self.assertEqual(UseCaseSpecification.objects.count(),0)

    @patch('apps.modeling.views.plantuml.render')
    def test_guardado_reintentado_no_duplica_y_rechaza_cambio_de_payload(self,render):
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        render.return_value=RenderResult(SVG,'hash','plantuml',False,SVG.encode())
        headers={'HTTP_X_REQUEST_ID':str(uuid.uuid4())}
        url=reverse('modeling:api_save')
        first=self.post(url,SPEC,**headers);again=self.post(url,SPEC,**headers)
        self.assertEqual(first.status_code,200);self.assertEqual(again.status_code,200)
        self.assertEqual(first.json()['id'],again.json()['id'])
        self.assertEqual(UseCaseSpecification.objects.count(),1)
        self.assertEqual(render.call_count,1)
        conflict=self.post(url,{**SPEC,'name':'Otro nombre'},**headers)
        self.assertEqual(conflict.status_code,409)

    def test_reintento_explicito_final_no_reabre_ni_vuelve_a_puntuar(self):
        questions=list(self.version.questions.filter(quality='high').order_by('round_number'))
        url=reverse('interviews:api_ask',args=[self.attempt.id])
        for question in questions:
            r=self.post(url,{'question_id':str(question.id)})
            self.assertEqual(r.status_code,200)
        self.attempt.refresh_from_db();score=self.attempt.interview_score
        legacy=self.post(url,{'question_id':str(questions[-1].id)})
        self.assertEqual(legacy.status_code,400)
        explicit=self.post(url,{'question_id':str(questions[-1].id)},HTTP_X_REQUEST_ID=str(uuid.uuid4()))
        self.assertEqual(explicit.status_code,200);self.assertTrue(explicit.json()['replayed'])
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.interview_score,score)
        self.assertEqual(self.attempt.log_entries.count(),9)

    @patch('apps.modeling.views.perf_counter',side_effect=[10,12.2])
    @patch('apps.modeling.views.plantuml.render')
    def test_png_certifica_svg_primero_e_informa_latencia_total(self,render,clock):
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        render.side_effect=[RenderResult(SVG,'hash','plantuml',False,SVG.encode(),duration_ms=1300),RenderResult('','hash','plantuml',False,b'png','png',900)]
        r=self.post(reverse('modeling:api_generate'),{**SPEC,'format':'png'})
        self.assertEqual(r.status_code,200)
        self.assertEqual([c.args[1] for c in render.call_args_list],['svg','png'])
        self.assertEqual(r.json()['duration_ms'],900)
        self.assertEqual(r.json()['svg_certification_ms'],1300)
        self.assertEqual(r.json()['total_duration_ms'],2200)
