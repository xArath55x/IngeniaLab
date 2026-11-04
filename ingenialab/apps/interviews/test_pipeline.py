"""ACT-211A1: entrevista -> clasificación -> modelo, bitácora y aislamiento."""
from copy import deepcopy
from io import StringIO
import json
import os
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.classification.services import available_requirements
from apps.interviews.models import ScenarioVersion, StudentAttempt
from apps.modeling.models import UseCaseSpecification
from integrations.plantuml.service import RenderResult

SVG='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><text x="1" y="20">Prueba</text></svg>'


def valid_ai(payload,*args):
    segments=deepcopy(payload['catalog_segments'])
    for segment in segments:
        if not segment.get('req'):segment['text']='Conversacion de IA persistida.'
    return {'segments':segments}


@override_settings(INGENIALAB_MODULES=['interviews','classification','modeling'],INGENIALAB_AI_MODE='chat_completions',INGENIALAB_AI_ENDPOINT='http://127.0.0.1:9999/v1/chat/completions',INGENIALAB_AI_MODEL='prueba',INGENIALAB_AI_TIMEOUT=1.2,PLANTUML_ALLOW_FALLBACK=False)
class ElicitationPipelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_ingenialab',stdout=StringIO())
        cls.user=get_user_model().objects.create_user('pipeline',password='Prueba211A1!')
        cls.other=get_user_model().objects.create_user('pipeline-otro')
        cls.version=ScenarioVersion.objects.get(scenario_code='ESC-BIBLIOTECA-01')

    def setUp(self):
        self.client.force_login(self.user)
        self.attempt=StudentAttempt.objects.create(user=self.user,version=self.version)

    def post(self,url,data):return self.client.post(url,json.dumps(data),content_type='application/json')

    def ask(self,q):return self.post(reverse('interviews:api_ask',args=[self.attempt.id]),{'question_id':str(q.id)})

    def finish(self):
        for q in self.version.questions.filter(quality='high').order_by('round_number'):
            r=self.ask(q);self.assertEqual(r.status_code,200)
        self.attempt.refresh_from_db();self.assertEqual(self.attempt.status,StudentAttempt.CLASSIFYING)

    def payload(self):
        return {'name':'Registrar préstamo','system_name':'Biblioteca','primary_actors':['Bibliotecario'],'secondary_actors':[],'preconditions':'El bibliotecario inició sesión.','main_flow':['El bibliotecario captura la solicitud.','El sistema registra el préstamo.'],'alternate_flows':[],'postconditions':'Préstamo registrado.','relations':[],'attempt_id':str(self.attempt.id)}

    @patch('integrations.ai.dialogue._request',side_effect=valid_ai)
    def test_recorrido_ia_clasificacion_modelado_y_reapertura(self,provider):
        self.finish();self.assertEqual(self.attempt.log_entries.count(),9)
        self.assertFalse(self.attempt.log_entries.exclude(response_source='ai').exists())
        r=self.client.get(reverse('interviews:interview',args=[self.attempt.id]))
        self.assertContains(r,reverse('classification:classify',args=[self.attempt.id]))
        for req in available_requirements(self.attempt):
            r=self.post(reverse('classification:api_classify',args=[self.attempt.id]),{'requirement_id':str(req.id),'category':req.expected_type})
            self.assertEqual(r.status_code,200);self.assertTrue(r.json()['is_correct']);self.assertTrue(r.json()['explanation'])
        self.attempt.refresh_from_db();self.assertEqual(self.attempt.classification_precision,100)
        url=reverse('classification:classify',args=[self.attempt.id])
        self.assertContains(self.client.get(url),'?attempt='+str(self.attempt.id))
        r=self.client.get(reverse('modeling:new')+'?attempt='+str(self.attempt.id))
        self.assertEqual(r.context['reference_attempt'],self.attempt)
        self.assertTrue(r.context['guide'][0]['requirements'])
        result=RenderResult(SVG,'hash-prueba','plantuml',False,SVG.encode())
        with patch('apps.modeling.views.plantuml.render',return_value=result):r=self.post(reverse('modeling:api_save'),self.payload())
        self.assertEqual(r.status_code,200);uc=UseCaseSpecification.objects.get(id=r.json()['id'])
        self.assertEqual(uc.attempt,self.attempt);self.assertEqual(uc.user,self.user);self.assertEqual(uc.diagram.svg,SVG)
        calls=provider.call_count;self.client.logout();self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(reverse('modeling:edit',args=[uc.id])).status_code,200)
        self.assertEqual(provider.call_count,calls);self.assertEqual(self.attempt.log_entries.count(),9)

    @patch('integrations.ai.dialogue._request',side_effect=TimeoutError('simulado'))
    def test_timeout_no_es_500_y_permite_clasificar(self,provider):
        self.finish();self.assertFalse(self.attempt.log_entries.exclude(fallback_reason='timeout').exists())
        req=available_requirements(self.attempt).first();self.assertIsNotNone(req)
        r=self.post(reverse('classification:api_classify',args=[self.attempt.id]),{'requirement_id':str(req.id),'category':req.expected_type})
        self.assertEqual(r.status_code,200);self.assertTrue(r.json()['is_correct'])

    @override_settings(INGENIALAB_AI_MODE='catalog')
    def test_snapshot_inmutable_y_reporte_usa_respuesta_guardada(self):
        q=self.version.questions.get(round_number=1,quality='high');self.assertEqual(self.ask(q).status_code,200)
        entry=self.attempt.log_entries.get();expected=entry.answer_text
        q.answer_segments=[{'text':'Catalogo cambiado despues','req':None}];q.save()
        from apps.interviews.services import serialize_entry, requirement_index
        entry.refresh_from_db();serialized=serialize_entry(entry,requirement_index(self.version))
        self.assertEqual(' '.join(s['text'] for s in serialized['segments']),expected)
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        from apps.progress.views import _report_data
        rows,_,_=_report_data(self.user);self.assertEqual(rows[0]['log'][0]['answer'],expected)

    @override_settings(INGENIALAB_AI_MODE='catalog')
    def test_no_se_acepta_entrevista_ajena_o_identificador_invalido(self):
        foreign=StudentAttempt.objects.create(user=self.other,version=self.version,status=StudentAttempt.CLASSIFYING)
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        self.assertEqual(self.client.get(reverse('modeling:new')+'?attempt='+str(foreign.id)).status_code,404)
        self.assertEqual(self.client.get(reverse('modeling:new')+'?attempt=no-es-uuid').status_code,400)
        payload=self.payload();payload['attempt_id']=str(foreign.id)
        self.assertEqual(self.post(reverse('modeling:api_validate'),payload).status_code,400)
        self.assertEqual(self.client.get(reverse('classification:classify',args=[foreign.id])).status_code,404)

    def test_sesion_expirada_no_invoca_ia(self):
        self.client.logout()
        with patch('integrations.ai.dialogue._request') as provider:r=self.ask(self.version.questions.first())
        self.assertEqual(r.status_code,401);provider.assert_not_called()

    @override_settings(INGENIALAB_AI_MODE='catalog')
    def test_uuid_de_requisito_mal_formado_devuelve_400(self):
        self.attempt.status=StudentAttempt.CLASSIFYING;self.attempt.save()
        r=self.post(reverse('classification:api_classify',args=[self.attempt.id]),{'requirement_id':'no-es-uuid','category':'RF'})
        self.assertEqual(r.status_code,400)

    @skipUnless(os.environ.get('INGENIALAB_TEST_PLANTUML')=='1','Requiere Java, Graphviz y JAR reales.')
    @override_settings(INGENIALAB_AI_MODE='catalog')
    def test_recorrido_con_diagrama_plantuml_real(self):
        self.finish()
        with tempfile.TemporaryDirectory() as cache,override_settings(PLANTUML_CACHE_DIR=cache):r=self.post(reverse('modeling:api_save'),self.payload())
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['engine'],'plantuml')
        uc=UseCaseSpecification.objects.get(id=r.json()['id']);self.assertEqual(uc.attempt,self.attempt)
        self.assertIn('Bibliotecario',uc.diagram.svg)
