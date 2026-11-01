"""Frozen real-CLI comparison on synthetic requests; never account enrollment."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'plugins/billfit/tests/fixtures/care-program-names-v1.json'
PROGRAM = 'plugins/billfit/skills/billfit/scripts/billfit_cli.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if args.output.exists():
        parser.error('Use a new observation file; existing evidence is retained.')
    cases = []
    for label, canonical in fixture['recognized'].items():
        cases.append(('qualified_label', label, {**fixture['synthetic_household'],
                     'enrolled_public_programs': [label]}, canonical))
    for label in fixture['unresolved']:
        cases.append(('unresolved_label', label, {**fixture['synthetic_household'],
                     'enrolled_public_programs': [label]}, None))
    for label, programs in [('wrong_container', 'SNAP'), ('null_member', [None]),
                            ('numeric_member', [1]), ('empty_name', ['']),
                            ('too_many', ['SNAP'] * 33), ('too_long', ['SYNTHETIC_NAME' * 20])]:
        cases.append(('invalid_input', label, {**fixture['synthetic_household'],
                     'enrolled_public_programs': programs}, 'INVALID_PUBLIC_PROGRAMS'))
    for income, field, status in [(0, 'care', 'likely_eligible'), (43280, 'care', 'likely_eligible'),
                                  (43280.5, 'fera', 'needs_official_confirmation'),
                                  (43281, 'fera', 'likely_eligible'), (54100, 'fera', 'likely_eligible'),
                                  (54100.01, 'fera', 'likely_not_eligible_by_income')]:
        cases.append(('income_control', str(income), {'household_size': 2,
                     'gross_annual_household_income': income}, (field, status)))
    observations = []
    with tempfile.TemporaryDirectory(prefix='billfit-name-comparison-') as temporary:
        path = Path(temporary) / 'request.json'
        for category, name, request, expected in cases:
            path.write_text(json.dumps(request), encoding='utf-8')
            started = time.monotonic()
            try:
                run = subprocess.run([sys.executable, str(checkout / PROGRAM), 'assistance',
                                      '--input-file', str(path)], text=True, capture_output=True, timeout=15)
                try:
                    result = json.loads(run.stdout)
                except ValueError:
                    result = None
                checks = {'json_response': isinstance(result, dict), 'no_traceback': not run.stderr}
                if category == 'qualified_label':
                    checks['recognized_correctly'] = (run.returncode == 0 and isinstance(result, dict)
                        and result.get('care', {}).get('matching_programs') == [expected]
                        and result.get('care', {}).get('basis') == 'categorical_program')
                elif category == 'unresolved_label':
                    checks['not_auto_eligible'] = (run.returncode == 0 and isinstance(result, dict)
                        and result.get('care', {}).get('status') != 'likely_eligible')
                    checks['visible_review'] = (isinstance(result, dict)
                        and result.get('categorical_program_review', {}).get('status') == 'needs_confirmation'
                        and 'ASSISTANCE_PROGRAM_CONFIRMATION' in {g['id'] for g in result.get('human_gates', [])})
                elif category == 'invalid_input':
                    checks['domain_error'] = (run.returncode == 2 and isinstance(result, dict)
                        and result.get('error', {}).get('code') == expected)
                else:
                    field, status = expected
                    checks['unchanged_income_decision'] = (run.returncode == 0 and isinstance(result, dict)
                        and result.get(field, {}).get('status') == status)
                stderr = run.stderr.replace(str(checkout), '$CHECKOUT').replace(temporary, '$TEMPORARY')
                observations.append({'category': category, 'name': name, 'request': request,
                    'expected': expected, 'exit_code': run.returncode, 'result': result,
                    'stdout': run.stdout, 'stderr': stderr,
                    'original_stderr_sha256': hashlib.sha256(run.stderr.encode()).hexdigest(),
                    'seconds': round(time.monotonic() - started, 6), 'checks': checks,
                    'passed': all(checks.values())})
            except subprocess.TimeoutExpired:
                observations.append({'category': category, 'name': name, 'request': request,
                    'expected': expected, 'passed': False, 'status': 'CLI_TIMEOUT',
                    'seconds': round(time.monotonic() - started, 6)})
    summary = {}
    for category in ('qualified_label', 'unresolved_label', 'invalid_input', 'income_control'):
        rows = [item for item in observations if item['category'] == category]
        summary[category] = {'total': len(rows), 'passed': sum(item['passed'] for item in rows)}
    hashes = {}
    for relative in (PROGRAM, 'plugins/billfit/skills/billfit/scripts/billfit_core.py',
                     'plugins/billfit/skills/billfit/scripts/assistance_programs.py',
                     'plugins/billfit/skills/billfit/data/care_fera_2026-06-01.json',
                     'plugins/billfit/skills/billfit/data/pge_residential_rates_2026-03-01.json'):
        if (checkout / relative).is_file():
            hashes[relative] = hashlib.sha256((checkout / relative).read_bytes()).hexdigest()
    receipt = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'checkout_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip(),
        'protocol': fixture['protocol'], 'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        'evaluator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'input_source': 'SYNTHETIC', 'new_model_calls': 0, 'total_cost_usd': None,
        'enrollment_actions': 0, 'independent_human': False, 'runtime_hashes': hashes,
        'summary': summary, 'observations': observations,
        'limitations': fixture['limitations'] + ['Elapsed time is one local CLI observation, not a performance population estimate']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
