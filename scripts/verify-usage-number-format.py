"""Run frozen synthetic files through the real CLI; never a model/client trial."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'plugins/billfit/tests/fixtures/usage-number-format-v1.json'
START = '2026-07-06T12:00:00-07:00'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_case(suffix, value=1, duration=60):
    if suffix == '.json':
        return json.dumps({'intervals': [{'start': START, 'kwh': value, 'duration_minutes': duration}]})
    target = io.StringIO(newline='')
    writer = csv.writer(target)
    writer.writerow(['timestamp', 'duration minutes', 'kWh'])
    writer.writerow([START, duration, value])
    return target.getvalue()


def cases(fixture):
    for suffix in ['.json', '.csv']:
        bad_energy = fixture['invalid_energy'] if suffix == '.json' else fixture['invalid_energy'][:14]
        for index, value in enumerate(bad_energy):
            yield f'energy-reject-{suffix[1:]}-{index}', suffix, file_case(suffix, value), {'error': 'INVALID_USAGE_VALUE'}
        for index, value in enumerate(fixture['valid_energy']):
            yield f'energy-accept-{suffix[1:]}-{index}', suffix, file_case(suffix, value['input']), {'kwh': value['kwh'], 'minutes': 60}
        bad_duration = fixture['invalid_duration'] if suffix == '.json' else fixture['invalid_duration'][:6]
        for index, value in enumerate(bad_duration):
            yield f'duration-reject-{suffix[1:]}-{index}', suffix, file_case(suffix, duration=value), {'error': 'INVALID_INTERVAL_DURATION'}
        for index, value in enumerate(fixture['valid_duration']):
            yield f'duration-accept-{suffix[1:]}-{index}', suffix, file_case(suffix, duration=value['input']), {'kwh': 1, 'minutes': value['minutes']}
    for index, row in enumerate(fixture['extra_csv_records']):
        yield f'csv-surplus-{index}', '.csv', 'timestamp,duration minutes,kWh\n' + row + '\n', {'error': 'CSV_ROW_WIDTH_MISMATCH'}
    for index, (energy, seconds, expected) in enumerate([
        ('1,23', '900', {'error': 'INVALID_USAGE_VALUE'}),
        ('$250', '900', {'error': 'INVALID_USAGE_VALUE'}),
        ('2_50', '900', {'error': 'INVALID_USAGE_VALUE'}),
        ('1e-400', '900', {'error': 'INVALID_USAGE_VALUE'}),
        ('250', '9,00', {'error': 'INVALID_INTERVAL_DURATION'}),
        ('250', '900', {'kwh': .25, 'minutes': 15})]):
        text = ('<feed><ReadingType><uom>72</uom><powerOfTenMultiplier>0</powerOfTenMultiplier></ReadingType>'
                '<IntervalBlock><IntervalReading><timePeriod><start>1783350000</start><duration>' + seconds +
                '</duration></timePeriod><value>' + energy + '</value></IntervalReading></IntervalBlock></feed>')
        yield f'xml-{index}', '.xml', text, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output; prior observations are never overwritten.')
    repository = args.repository.resolve()
    cli = repository / 'plugins/billfit/skills/billfit/scripts/billfit_cli.py'
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    rows = []
    with tempfile.TemporaryDirectory(prefix='billfit-number-synthetic-') as temporary:
        directory = Path(temporary)
        for identifier, suffix, content, expected in cases(fixture):
            path = directory / (identifier + suffix)
            path.write_text(content, encoding='utf-8', newline='')
            source = path.read_bytes()
            request = directory / 'request.json'
            request.write_text(json.dumps({'usage_file': str(path)}), encoding='utf-8')
            started = time.perf_counter()
            process = subprocess.run([sys.executable, str(cli), 'parse', '--input-file', str(request)],
                                     capture_output=True, text=True, encoding='utf-8', timeout=20, cwd=repository)
            elapsed = time.perf_counter() - started
            body = json.loads(process.stdout)
            error = body.get('error', {}).get('code')
            preview = body.get('preview') or [{}]
            checks = {'source_unchanged': source == path.read_bytes(),
                      'no_input_in_error': not error or 'IGNORED_SYNTHETIC_CELL' not in json.dumps(body)}
            if 'error' in expected:
                checks['reject_without_values'] = (process.returncode == 2 and error == expected['error']
                    and 'summary' not in body and 'preview' not in body)
            else:
                checks['preserved_values'] = (process.returncode == 0 and error is None
                    and body.get('summary', {}).get('total_kwh') == expected['kwh']
                    and preview[0].get('duration_minutes') == expected['minutes'])
            if 'source' in body:
                body['source'] = '$SYNTHETIC_FILE'
            rows.append({'id': identifier, 'source_sha256': digest(source), 'expected': expected,
                         'exit': process.returncode, 'elapsed_seconds': elapsed, 'result': body,
                         'stderr_sha256': digest(process.stderr.encode('utf-8')), 'checks': checks,
                         'passed': all(checks.values())})
    rejected = [row for row in rows if 'error' in row['expected']]
    accepted = [row for row in rows if 'error' not in row['expected']]
    receipt = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'checkout_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True).strip(),
        'runtime_sha256': digest((repository / 'plugins/billfit/skills/billfit/scripts/billfit_usage.py').read_bytes().replace(b'\r\n', b'\n')),
        'fixture_sha256': digest(FIXTURE.read_bytes().replace(b'\r\n', b'\n')),
        'evaluator_sha256': digest(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
        'environment': {'python': sys.version.split()[0], 'platform': sys.platform},
        'input_kind': 'synthetic', 'new_model_calls': 0,
        'summary': {'requests': len(rows), 'passed': sum(row['passed'] for row in rows),
            'invalid_rejected_correctly': sum(row['passed'] for row in rejected), 'invalid_n': len(rejected),
            'valid_preserved_correctly': sum(row['passed'] for row in accepted), 'valid_n': len(accepted),
            'elapsed_seconds': sum(row['elapsed_seconds'] for row in rows)},
        'observations': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(receipt, target, ensure_ascii=False, indent=2)
        target.write('\n')
    print(json.dumps(receipt['summary']))
    return 0 if all(row['passed'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
