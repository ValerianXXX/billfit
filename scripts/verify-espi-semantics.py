"""Run the frozen synthetic reading-semantics cases through the actual CLI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
TESTS=ROOT/'plugins/billfit/tests'
sys.path.insert(0,str(TESTS))
from _espi_semantics import CASES,FIXTURE,fixture_xml
CLI=ROOT/'plugins/billfit/skills/billfit/scripts/billfit_cli.py'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise SystemExit('Observation already exists')
    rows=[];start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='billfit-espi-') as raw:
        directory=Path(raw);source=directory/'synthetic.xml';request=directory/'request.json'
        request.write_text(json.dumps({'usage_file':str(source)}),encoding='utf8')
        for case in CASES:
            data=fixture_xml(case).encode('utf8');source.write_bytes(data)
            run=subprocess.run([sys.executable,str(CLI),'parse','--input-file',str(request)],
                               capture_output=True,text=True,timeout=20,check=False)
            response=json.loads(run.stdout)
            warnings=[w for w in response.get('warnings',[]) if w.startswith('ESPI_')]
            gates=[g['id'] for g in response.get('human_gates',[])]
            error=response.get('error',{}).get('code')
            kwh=response.get('summary',{}).get('total_kwh')
            passed=(run.returncode==2 and error==case['error']) if case['expected']=='reject' else (
                run.returncode==0 and kwh==case.get('expected_kwh',.25) and
                ((any(case['marker'] in w for w in warnings) and 'USAGE_QUALITY_REVIEW' in gates)
                 if case['expected']=='review' else not warnings))
            assert source.read_bytes()==data
            rows.append({'id':case['id'],'expected':case['expected'],'passed':passed,'exit_code':run.returncode,
                'error_code':error,'total_kwh':kwh,'warnings':warnings,'human_gates':gates,
                'input_sha256':hashlib.sha256(data).hexdigest()})
    summary={kind:{'total':sum(row['expected']==kind for row in rows),
                   'passed':sum(row['expected']==kind and row['passed'] for row in rows)}
             for kind in ('reject','review','accept')}
    result={'observed_at_utc':datetime.now(timezone.utc).isoformat(),
            'runtime_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'fixture_sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Frozen synthetic actual CLI requests; not utility certification or customer accuracy.',
            'new_model_calls':0,'elapsed_seconds':round(time.monotonic()-start,3),'summary':summary,'cases':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'summary':summary,'elapsed_seconds':result['elapsed_seconds']}))

if __name__=='__main__':main()
