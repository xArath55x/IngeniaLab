"""ACT-209: latencia real con SVG frio, PNG tras SVG y PNG totalmente frio."""
import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
from django.test.utils import override_settings
from integrations.plantuml.builder import build_usecase_diagram
from integrations.plantuml.service import render,PlantUMLError

SCENARIOS=[
 {'id':'minimo','name':'Reservar libro','system_name':'Biblioteca','primary_actors':['Estudiante'],'secondary_actors':[],'relations':[]},
 {'id':'biblioteca','name':'Registrar préstamo','system_name':'Biblioteca UAZ','primary_actors':['Bibliotecario'],'secondary_actors':['Servicio de correo'],'relations':[{'type':'include','target':'Verificar disponibilidad'},{'type':'extend','target':'Notificar rechazo'}]},
 {'id':'varios_actores','name':'Gestionar reservación','system_name':'Sistema de reservaciones','primary_actors':['Estudiante','Encargado'],'secondary_actors':['Servicio de correo','Control de acceso'],'relations':[{'type':'include','target':'Verificar identidad'},{'type':'include','target':'Consultar disponibilidad'},{'type':'extend','target':'Cancelar solicitud'},{'type':'extend','target':'Notificar rechazo'}]}
]
def version(command):
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=5)
        return (p.stdout+p.stderr).strip().splitlines()[0]
    except Exception as e:return type(e).__name__
def summary(rows,key):
    values=sorted(row[key] for row in rows if key in row)
    if not values:return None
    return {'n':len(values),'min_ms':min(values),'max_ms':max(values),'mean_ms':round(sum(values)/len(values),3),'p95_ms':values[max(0,math.ceil(.95*len(values))-1)]}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',type=int,default=3);parser.add_argument('--output',required=True);parser.add_argument('--strict',action='store_true');args=parser.parse_args()
    if not 1<=args.runs<=20:parser.error('Usa entre 1 y 20 repeticiones.')
    rows=[];started=datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory() as parent,override_settings(PLANTUML_ALLOW_FALLBACK=False):
        for scenario in SCENARIOS:
            for i in range(args.runs):
                code=build_usecase_diagram({**scenario,'name':scenario['name']+f' {i+1}'})
                shared=Path(parent)/scenario['id']/str(i)
                for mode,format,cache in [('svg_cold','svg',shared),('png_after_svg','png',shared),('png_fully_cold','png',shared/'independent')]:
                    row={'scenario':scenario['id'],'trial':i+1,'mode':mode,'format':format,'actors':len(scenario['primary_actors'])+len(scenario['secondary_actors']),'use_cases':1+len(scenario['relations'])}
                    with override_settings(PLANTUML_CACHE_DIR=cache):
                        try:
                            t=time.perf_counter();cold=render(code,format);row['generation_ms']=round((time.perf_counter()-t)*1000,3)
                            t=time.perf_counter();hit=render(code,format);row['cache_ms']=round((time.perf_counter()-t)*1000,3)
                            row.update({'engine':cold.engine,'code_hash':cold.code_hash,'bytes':len(cold.data),'cache_verified':not cold.cached and hit.cached and hit.data==cold.data,'under_2s':row['generation_ms']<2000,'cache_under_50ms':row['cache_ms']<50})
                            row['passed']=row['engine']=='plantuml' and row['cache_verified'] and row['under_2s'] and row['cache_under_50ms']
                        except PlantUMLError as e:row.update({'passed':False,'error':e.code,'message':str(e)})
                    rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    jar=Path(settings.PLANTUML_JAR)
    tracked=['apps/modeling/forms.py','apps/modeling/validators.py','apps/modeling/views.py','integrations/plantuml/builder.py','integrations/plantuml/service.py']
    report={'activity':'ACT-209','started_at_utc':started,'environment':{'python':platform.python_version(),'django':django.get_version(),'os':platform.system(),'java':version([settings.PLANTUML_JAVA,'-version']),'graphviz':version([settings.PLANTUML_DOT,'-V']),'jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest() if jar.exists() else None,'render_timeout_s':settings.PLANTUML_TIMEOUT,'jvm_fast_start':settings.PLANTUML_FAST_START},'measurement_scope':'Tiempo de pared del adaptador local; excluye red y pintura del navegador. PNG totalmente frio incluye certificacion SVG y subproceso PNG. PLANTUML_FAST_START reduce compilacion JVM para subprocesos cortos. Un proceso Java nuevo en cada MISS; cache de SO no controlada. Ejecucion secuencial, no ensayo de carga.','samples':rows,'sample_count':len(rows),'all_targets_met':all(r['passed'] for r in rows),'summaries':{mode:{'generation':summary([r for r in rows if r['mode']==mode],'generation_ms'),'cache':summary([r for r in rows if r['mode']==mode],'cache_ms')} for mode in ('svg_cold','png_after_svg','png_fully_cold')},'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in tracked}}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 1 if args.strict and not report['all_targets_met'] else 0
if __name__=='__main__':raise SystemExit(main())
