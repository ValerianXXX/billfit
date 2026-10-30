"""Measure only committed synthetic fixtures; never accepts a user bill path."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/billfit/skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
from bill_input import extract_bill_fields
from billfit_errors import BillFitError

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=['image', 'pdf'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    handle = args.output.open('x', encoding='utf-8', newline='\n')
    directory = ROOT / 'plugins/billfit/tests/fixtures/bill-input-v2'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['synthetic_only'] is True
    engine = None
    if args.kind == 'image':
        command = os.environ.get('BILLFIT_TESSERACT_PATH', '')
        engine = subprocess.run([command, '--version'], capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()[0]
    rows = []
    try:
        for case in manifest['cases']:
            if case['kind'] != args.kind:
                continue
            fixture = directory / case['file']
            assert hashlib.sha256(fixture.read_bytes()).hexdigest() == case['sha256']
            started = time.perf_counter()
            try:
                result = extract_bill_fields(str(fixture))
                actual = {key: Counter(row['value'] for row in result['candidates'] if row['field'] == key) for key in case['expected']}
                missing = {key: list((Counter(expected) - actual[key]).elements()) for key, expected in case['expected'].items()}
                unexpected = {key: list((actual[key] - Counter(expected)).elements()) for key, expected in case['expected'].items()}
                missing = {key: values for key, values in missing.items() if values}
                unexpected = {key: values for key, values in unexpected.items() if values}
                evidence = all(row['source']['sha256'] == case['sha256'] and row['source']['page'] in (1, 2)
                               and row['status'] == 'NEEDS_USER_CONFIRMATION' for row in result['candidates'])
                if args.kind == 'image':
                    evidence = evidence and all(row['source']['bbox'] and 0 <= row['source']['bbox'][0] < row['source']['bbox'][2] <= case['pixel_size'][0]
                        and 0 <= row['source']['bbox'][1] < row['source']['bbox'][3] <= case['pixel_size'][1] for row in result['candidates'])
                else:
                    evidence = evidence and Counter(row['source']['page'] for row in result['candidates']) == Counter({1: 5, 2: 5})
                visible_rejections = set(case['expected_rejected_fields']).issubset(
                    {row['field'] for row in result.get('unresolved_fields', [])})
                passed = not missing and not unexpected and evidence and sorted(result['conflicting_fields']) == sorted(case['expected_conflicts'])
                passed = passed and visible_rejections and not result['automatic_confirmation'] and not result['automatic_calculation']
                rows.append({'id': case['id'], 'status': 'PASS' if passed else 'FAILED', 'missing': missing,
                             'unexpected': unexpected, 'evidence_valid': evidence, 'visible_rejections': visible_rejections, 'result': result})
            except BillFitError as error:
                rows.append({'id': case['id'], 'status': 'BLOCKED', 'code': error.code})
            rows[-1]['milliseconds'] = round((time.perf_counter() - started) * 1000, 3)
        files = ['bill_input.py', 'bill_ocr.py']
        hashes = {name: hashlib.sha256((SCRIPTS/name).read_text(encoding='utf-8').replace('\r\n', '\n').encode()).hexdigest()
                  for name in files if (SCRIPTS/name).exists()}
        receipt = {'observedAt': datetime.now(timezone.utc).isoformat(), 'kind': args.kind, 'synthetic_only': True,
                   'python': platform.python_version(), 'platform': platform.system(), 'engine': engine,
                   'sourceLFHashes': hashes, 'manifestSha256': hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest(),
                   'cases': len(rows), 'passed': sum(row['status'] == 'PASS' for row in rows),
                   'cloud_calls': 0, 'actual_dollar_cost': None, 'results': rows,
                   'limits': ['Authored synthetic fixtures, not customer bills or population accuracy',
                              'OCR confidence is uncalibrated; all fields still need user confirmation',
                              'No tariff update, calculator activation, account action or deployment']}
        json.dump(receipt, handle, indent=2); handle.write('\n')
        print(json.dumps({key: receipt[key] for key in ('kind', 'cases', 'passed', 'engine', 'python')}))
        return 0 if receipt['passed'] == len(rows) else 1
    finally:
        handle.close()

if __name__ == '__main__':
    raise SystemExit(main())
