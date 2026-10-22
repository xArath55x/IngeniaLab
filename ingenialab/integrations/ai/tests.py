"""ACT-211A1: contrato IA, espera acotada y fallback con mocks."""
from copy import deepcopy
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from django.test import SimpleTestCase, override_settings
from . import dialogue

AI = override_settings(INGENIALAB_AI_MODE='chat_completions', INGENIALAB_AI_ENDPOINT='http://127.0.0.1:9999/v1/chat/completions', INGENIALAB_AI_MODEL='modelo-prueba', INGENIALAB_AI_API_KEY='secreto-prueba', INGENIALAB_AI_TIMEOUT=1.2)
CATALOG = [{'text':'Hola, gracias por preguntar.','req':None}, {'text':'El sistema registra préstamos.','req':'B01'}]


def question():
    return SimpleNamespace(text='¿Qué necesita?', version=SimpleNamespace(title='Biblioteca'), answer_segments=deepcopy(CATALOG))


@AI
class DialogueAdapterTests(SimpleTestCase):
    @patch('integrations.ai.dialogue._request')
    def test_ia_contextualiza_sin_cambiar_requisitos(self, request):
        segments=deepcopy(CATALOG);segments[0]['text']='Te explico nuestra necesidad.'
        request.return_value={'segments':segments}
        result=dialogue.answer(question())
        self.assertEqual(result.source,'ai');self.assertEqual(result.segments,segments)

    @patch('integrations.ai.dialogue._request', side_effect=TimeoutError('simulado'))
    def test_timeout_mockeado_activa_catalogo_antes_de_1_8s(self, request):
        start=time.monotonic();result=dialogue.answer(question())
        self.assertLess(time.monotonic()-start,1.8)
        self.assertEqual((result.source,result.reason),('catalog','timeout'))
        self.assertEqual(result.segments,CATALOG)

    @patch('integrations.ai.dialogue._request', side_effect=URLError('sin red'))
    def test_error_red_activa_catalogo(self, request):
        self.assertEqual(dialogue.answer(question()).reason,'unavailable')

    @patch('integrations.ai.dialogue._request')
    def test_rechaza_respuesta_invalida_y_requisitos_inventados(self, request):
        changed=deepcopy(CATALOG);changed[1]['req']='INVENTADO'
        rewritten=deepcopy(CATALOG);rewritten[1]['text']='Otro requisito'
        for response in [None,{'segments':[]},{'segments':changed},{'segments':rewritten}]:
            with self.subTest(response=response):
                request.return_value=response
                self.assertEqual(dialogue.answer(question()).reason,'invalid_response')

    @override_settings(INGENIALAB_AI_TIMEOUT=0)
    @patch('integrations.ai.dialogue._request')
    def test_configuracion_invalida_no_llama_a_ia(self, request):
        self.assertEqual(dialogue.answer(question()).reason,'configuration');request.assert_not_called()

    @override_settings(INGENIALAB_AI_MODE='catalog')
    @patch('integrations.ai.dialogue._request')
    def test_catalogo_no_necesita_proveedor(self, request):
        r=dialogue.answer(question());self.assertEqual((r.source,r.reason),('catalog',''));request.assert_not_called()

    @override_settings(INGENIALAB_AI_TIMEOUT=0.03)
    def test_proveedor_lento_no_retiene_backend(self):
        release=threading.Event();done=threading.Event()
        def slow(*args):
            try:
                release.wait(2);return {'segments':deepcopy(CATALOG)}
            finally:done.set()
        try:
            with patch('integrations.ai.dialogue._request',side_effect=slow):
                start=time.monotonic();result=dialogue.answer(question())
                self.assertLess(time.monotonic()-start,1.8);self.assertEqual(result.reason,'timeout')
        finally:release.set();done.wait(2)

    @patch('integrations.ai.dialogue._SLOTS')
    def test_saturacion_no_crea_mas_hilos(self, slots):
        slots.acquire.return_value=False
        self.assertEqual(dialogue.answer(question()).reason,'busy')

    @patch('integrations.ai.dialogue.urllib.request.urlopen')
    def test_contrato_http_y_credencial_solo_backend(self, urlopen):
        response=MagicMock();response.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps({'segments':CATALOG})}}]}).encode()
        urlopen.return_value.__enter__.return_value=response
        self.assertEqual(dialogue.answer(question()).source,'ai')
        request=urlopen.call_args.args[0];body=json.loads(request.data)
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(request.get_header('Authorization'),'Bearer secreto-prueba')
        self.assertNotIn('secreto-prueba',json.dumps(body))
        self.assertEqual(set(json.loads(body['messages'][1]['content'])),{'scenario','question','catalog_segments'})

    @patch('integrations.ai.dialogue.urllib.request.urlopen')
    def test_respuesta_http_excesiva_se_descarta(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value=b'x'*(dialogue.MAX_BYTES+1)
        self.assertEqual(dialogue.answer(question()).reason,'unavailable')
