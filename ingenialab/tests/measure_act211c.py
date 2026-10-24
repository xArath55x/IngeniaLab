"""Mide una vista previa PNG fría sin tocar la BD del estudiante."""
import argparse
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT.parent/'05_Testing_And_Reports/ACT-211C/png_fases.json'))
    args=parser.parse_args()
    from django.conf import settings
    with tempfile.TemporaryDirectory() as tmp:
        settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':str(Path(tmp)/'probe.sqlite3')}}
        settings.PLANTUML_CACHE_DIR=Path(tmp)/'cache'
        import django
        django.setup()
        from django.core.management import call_command
        from django.contrib.auth import get_user_model
        from django.test import Client
        from apps.interviews.models import ScenarioVersion,StudentAttempt
        from apps.modeling.tests import SPEC
        call_command('migrate',interactive=False,stdout=StringIO())
        call_command('seed_ingenialab',stdout=StringIO())
        user=get_user_model().objects.create_user('medicion-211c')
        StudentAttempt.objects.create(user=user,version=ScenarioVersion.objects.first(),status='classifying')
        client=Client(HTTP_HOST='localhost');client.force_login(user)
        start=time.perf_counter()
        response=client.post('/modelado/api/generar/',json.dumps({**SPEC,'format':'png'}),content_type='application/json')
        elapsed=(time.perf_counter()-start)*1000
        data=response.json()
        result={'status':response.status_code,'http_total_ms':round(elapsed,3),'duration_ms':data.get('duration_ms'),'svg_certification_ms':data.get('svg_certification_ms'),'total_duration_ms':data.get('total_duration_ms'),'global_under_2s':elapsed<2000,'engine':data.get('engine')}
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
        return 0 if response.status_code==200 else 1


if __name__=='__main__':
    raise SystemExit(main())
