"""Runner Django de ACT-209 con resultados JSON y JUnit, sin dependencias extra."""
import json
import os
import platform
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import django
from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[];self.active={}
    def startTest(self,test):
        super().startTest(test)
        row={'id':test.id(),'status':'running','duration_ms':0,'subtests':[]}
        self.records.append(row);self.active[test.id()]=(row,time.perf_counter())
    def _record(self,test,status,detail=None):
        row=self.active[test.id()][0];row['status']=status
        if detail:row['detail']=detail
    def stopTest(self,test):
        row,start=self.active[test.id()];row['duration_ms']=round((time.perf_counter()-start)*1000,3)
        if row['status']=='running':row['status']='passed'
        super().stopTest(test)
    def addSuccess(self,test):super().addSuccess(test);self._record(test,'passed')
    def addFailure(self,test,err):super().addFailure(test,err);self._record(test,'failed',self._exc_info_to_string(err,test))
    def addError(self,test,err):super().addError(test,err);self._record(test,'error',self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):super().addSkip(test,reason);self._record(test,'skipped',reason)
    def addExpectedFailure(self,test,err):super().addExpectedFailure(test,err);self._record(test,'expected_failure',self._exc_info_to_string(err,test))
    def addUnexpectedSuccess(self,test):super().addUnexpectedSuccess(test);self._record(test,'unexpected_success')
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err is not None:
            detail=self._exc_info_to_string(err,test)
            self.active[test.id()][0]['subtests'].append({'id':str(subtest),'detail':detail})
            self._record(test,'failed',detail)

class EvidenceTextRunner(unittest.TextTestRunner):resultclass=EvidenceResult

class EvidenceRunner(DiscoverRunner):
    test_runner=EvidenceTextRunner
    def setup_test_environment(self,**kwargs):
        super().setup_test_environment(**kwargs)
        # Solo pruebas funcionales: no se mide ni certifica la criptografia.
        self.test_hashers=override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self.test_hashers.enable()
    def teardown_test_environment(self,**kwargs):
        self.test_hashers.disable()
        super().teardown_test_environment(**kwargs)
    def run_suite(self,suite,**kwargs):
        start=time.perf_counter();result=super().run_suite(suite,**kwargs)
        output=Path(os.environ.get('INGENIALAB_TEST_OUTPUT',str(settings.BASE_DIR.parent/'05_Testing_And_Reports'/'ACT-209'/'ejecucion')))
        output.mkdir(parents=True,exist_ok=True)
        counts=Counter(row['status'] for row in result.records)
        report={'activity':'ACT-209','executed_at_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'django':django.get_version(),'os':platform.system(),'real_engine_enabled':os.environ.get('INGENIALAB_TEST_PLANTUML')=='1','password_hasher_scope':'MD5 solo para pruebas funcionales; no cambia configuracion de la aplicacion','duration_s':round(time.perf_counter()-start,3),'tests_run':result.testsRun,'counts':dict(counts),'tests_successful':result.wasSuccessful(),'tests':result.records,'blocked_requirements':[{'id':'ACT209-IA-01','description':'Timeout del proveedor de IA y fallback al catalogo','status':'BLOCKED','reason':'La base ACT-207B no tiene proveedor de IA integrado. No se sustituye su evidencia con timeouts de PlantUML.'}]}
        (output/'resultados.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        root=ET.Element('testsuite',name='IngeniaLab ACT-209',tests=str(result.testsRun),failures=str(counts['failed']+counts['unexpected_success']),errors=str(counts['error']),skipped=str(counts['skipped']+counts['expected_failure']),time=str(report['duration_s']))
        for row in result.records:
            name=row['id'].rsplit('.',1);node=ET.SubElement(root,'testcase',classname=name[0],name=name[-1],time=f"{row['duration_ms']/1000:.6f}")
            tag={'failed':'failure','error':'error','skipped':'skipped','expected_failure':'skipped','unexpected_success':'failure'}.get(row['status'])
            if tag:ET.SubElement(node,tag,message=row['status']).text=row.get('detail','')
        ET.indent(root);ET.ElementTree(root).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
        self.log(f'Evidencia ACT-209: {output}')
        return result
