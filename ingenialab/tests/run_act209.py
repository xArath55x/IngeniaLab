"""ACT-209: ejecucion serial reproducible, cobertura y evidencia sin tocar datos."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(ROOT.parent/'05_Testing_And_Reports'/'ACT-209'/'repeticion'));p.add_argument('--runs',type=int,default=3);p.add_argument('--require-complete',action='store_true',help='Devuelve 2 si queda el requisito de IA bloqueado, aunque lo ejecutable pase.');args=p.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['INGENIALAB_TEST_PLANTUML']='1';env['INGENIALAB_TEST_OUTPUT']=str(out/'ejecucion')
    env['COVERAGE_FILE']=str(out/'coverage.data')
    commands=[('django_check',[sys.executable,'manage.py','check']),('migrations',[sys.executable,'manage.py','makemigrations','--check','--dry-run']),('tests',[sys.executable,'-m','coverage','run','manage.py','test','apps','integrations','--testrunner','tests.evidence_runner.EvidenceRunner','--verbosity','2']),('coverage_text',[sys.executable,'-m','coverage','report']),('coverage_json',[sys.executable,'-m','coverage','json','-o',str(out/'cobertura.json')]),('coverage_xml',[sys.executable,'-m','coverage','xml','-o',str(out/'cobertura.xml')]),('latency',[sys.executable,'tests/measure_act209.py','--runs',str(args.runs),'--strict','--output',str(out/'latencia.json')])]
    if shutil.which('node'):commands.append(('javascript',['node','tests/modeling-validation.cjs']))
    phases=[]
    for name,command in commands:
        print(f'ACT-209: {name}',flush=True)
        with (out/(name+'.log')).open('w',encoding='utf-8') as log:
            code=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=False).returncode
        phases.append({'phase':name,'exit_code':code,'log':name+'.log'})
    passed=all(phase['exit_code']==0 for phase in phases)
    tracked=['apps/modeling/forms.py','apps/modeling/validators.py','apps/modeling/views.py','apps/modeling/tests.py','integrations/plantuml/builder.py','integrations/plantuml/service.py','integrations/plantuml/tests.py','tests/evidence_runner.py','tests/measure_act209.py','tests/run_act209.py','config/settings.py']
    report={'activity':'ACT-209','timestamp_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'technical_checks_passed':passed,'activity_status':'PARTIAL_BLOCKED' if passed else 'FAILED_AND_BLOCKED','phases':phases,'blocked_requirement':{'id':'ACT209-IA-01','reason':'La base ACT-207B no integra un proveedor IA; no se puede ejecutar su timeout ni comprobar su fallback. Se requiere implementacion y contrato de CU-06.'},'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in tracked}}
    (out/'resumen_ejecucion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Comprobaciones tecnicas: '+('APROBADAS' if passed else 'CON FALLOS')+'. Timeout IA: BLOQUEADO. No se declara cierre completo de ACT-209.')
    return 1 if not passed else 2 if args.require_complete else 0
if __name__=='__main__':raise SystemExit(main())
