"""Native CLI path checks on a copied fixed synthetic fixture; no account or model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

from importlib.util import module_from_spec, spec_from_file_location

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'plugins/billfit/tests/fixtures/bill-input-v2'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('This explicit native check requires Windows.')
    if not os.environ.get('BILLFIT_TESSERACT_PATH'):
        parser.error('Configure an existing operator-approved native OCR executable first.')
    manifest_raw = (FIXTURES / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    profile = json.loads((FIXTURES.parent / 'bill-image-preparation-v1.json').read_text())
    assert manifest['synthetic_only'] and profile['synthetic_only']
    assert hashlib.sha256(manifest_raw).hexdigest() == profile['manifest_sha256']
    case = next(row for row in manifest['cases'] if row['id'] == 'skew-6-degrees')
    source = FIXTURES / case['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == case['sha256']
    spec = spec_from_file_location('billfit_existing_image_verifier', ROOT / 'scripts/verify-image-preparation-client.py')
    verifier = module_from_spec(spec)
    spec.loader.exec_module(verifier)
    rows = []
    report = {'observedAt': datetime.now(timezone.utc).isoformat(), 'protocol': 'BILLFIT_NATIVE_WINDOWS_PATHS_V1',
              'platform': platform.system(), 'python': platform.python_version(), 'syntheticOnly': True,
              'manifestSha256': profile['manifest_sha256'], 'newLlmCalls': 0, 'newCloudCalls': 0,
              'results': rows, 'independentHuman': False}
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        with tempfile.TemporaryDirectory(prefix='billfit-native-paths-') as temporary:
            owned = Path(temporary).resolve()
            for label, component in [('ascii', 'ascii'), ('spaces', 'with spaces'),
                                     ('unicode', '\u5408\u6210\u8d26\u5355 \u8bc1\u636e')]:
                directory = owned / component
                directory.mkdir()
                copy = directory / (component + '.png')
                shutil.copyfile(source, copy)
                parser_temp = directory / ('parser ' + component)
                parser_temp.mkdir()
                assert copy.resolve().is_relative_to(owned) and parser_temp.resolve().is_relative_to(owned)
                request = directory / 'request.json'
                request.write_text(json.dumps({'bill_file': str(copy), **profile['default_options'],
                    **profile['case_options'].get(case['id'], {})}), encoding='utf-8')
                env = {**os.environ, 'TEMP': str(parser_temp), 'TMP': str(parser_temp), 'PYTHONIOENCODING': 'utf-8'}
                started = time.perf_counter()
                completed = subprocess.run([sys.executable, str(ROOT / 'plugins/billfit/skills/billfit/scripts/billfit_cli.py'),
                    'extract-bill', '--input-file', str(request)], capture_output=True, timeout=40, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                row = {'case': label, 'exitCode': completed.returncode,
                       'milliseconds': round((time.perf_counter() - started)*1000, 3)}
                try:
                    value = json.loads(completed.stdout)
                    row['response'] = value
                    assert completed.returncode == 0
                    verifier.verify_result(value, case)
                    assert hashlib.sha256(copy.read_bytes()).hexdigest() == case['sha256']
                    assert not list(parser_temp.iterdir()), 'Parser left files in owned temporary parent'
                    row['status'] = 'PASS'
                    row['temporaryParserFilesRemoved'] = True
                    row['sourceUnchanged'] = True
                except Exception as error:
                    row['status'] = 'FAILED'
                    row['errorType'] = type(error).__name__
                    # Source snippets already live in the intentional tool result;
                    # raw stderr and uncontrolled local paths are not published.
                rows.append(row)
        report['ownedDirectoryRemoved'] = not owned.exists()
        report['status'] = 'PASS' if len(rows) == 3 and all(row['status'] == 'PASS' for row in rows) and report['ownedDirectoryRemoved'] else 'FAILED'
        report['limits'] = ['Fixed synthetic image only; no customer data or independent machine',
                            'Space/non-ASCII checks do not cover all long paths, UNC shares or filesystem policies']
        json.dump(report, output, indent=2, ensure_ascii=True)
        output.write('\n')
    print(json.dumps({'status': report['status'], 'cases': [{key: row[key] for key in ['case', 'exitCode', 'status']} for row in rows]}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
