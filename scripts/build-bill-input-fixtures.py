"""Build original, deterministic synthetic documents for input-boundary checks.

Authoring only: reportlab/pypdf/Poppler are not calculator or OCR dependencies.
Never reads an existing bill or image. Refuses to replace fixture files.
"""
from pathlib import Path
import hashlib
import json
import random
import subprocess
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'plugins/billfit/tests/fixtures/bill-input-v2'
VALUES = {'current_plan': ['E-TOU-D'], 'reported_energy_charge': ['12.34'],
          'reported_base_services_charge': ['0.79'], 'baseline_territory': ['X'], 'total_kwh': ['25.5']}
CASES = [
    ('clean', 0, False, {}), ('low-contrast-noise', 0, True, {}),
    ('skew-6-degrees', 6, False, {}), ('rotated-90-degrees', 90, False, {}),
    ('invalid-comma', 0, False, {'energy': '$12,34.56'}),
    ('credit', 0, False, {'energy': '$12.34 CR'}),
    ('unsupported-plan', 0, False, {'plan': 'E-TOU-D-NEM'}),
    ('conflicting-charge', 0, False, {'second_energy': '$56.78'}),
]

def main():
    if DEST.exists():
        raise SystemExit('Choose a new fixture version; existing files are immutable.')
    DEST.mkdir(parents=True)
    document = DEST / 'synthetic-layouts.pdf'
    pdf = canvas.Canvas(str(document), pagesize=(612, 612), invariant=1, pageCompression=1)
    pdf.setAuthor('ValerianXXX')
    pdf.setTitle('BillFit original synthetic input fixtures - not utility bills')
    manifest = []
    for name, rotation, noisy, changes in CASES:
        pdf.setFont('Helvetica', 9)
        pdf.drawString(32, 582, 'SYNTHETIC TEST ONLY / NOT A UTILITY BILL / NO CUSTOMER OR ACCOUNT DATA')
        pdf.drawString(32, 565, name)
        pdf.saveState()
        if noisy:
            rng = random.Random(20261030)
            pdf.setFillGray(.86)
            for _ in range(150):
                pdf.circle(rng.uniform(30, 580), rng.uniform(130, 540), rng.uniform(.2, 1.0), fill=1, stroke=0)
        pdf.translate(306, 306)
        pdf.rotate(rotation)
        pdf.translate(-306, -306)
        pdf.setFillGray(.62 if noisy else 0)
        pdf.setFont('Helvetica', 15)
        lines = ['Rate Schedule: ' + changes.get('plan', 'E-TOU-D'),
                 'Energy Charges ' + changes.get('energy', '$12.34'),
                 'Base Services Charge $0.79', 'Baseline Territory: X', 'Usage 25.5 kWh', 'Amount Due $98.76']
        if changes.get('second_energy'):
            lines.append('Energy Charges ' + changes['second_energy'])
        for index, line in enumerate(lines):
            pdf.drawString(65, 480 - 44 * index, line)
        pdf.restoreState()
        pdf.showPage()
        expected = {key: list(value) for key, value in VALUES.items()}
        rejected = []
        if name in {'invalid-comma', 'credit'}:
            expected['reported_energy_charge'] = []
            rejected = ['reported_energy_charge']
        if name == 'unsupported-plan':
            expected['current_plan'] = []
            rejected = ['current_plan']
        if name == 'conflicting-charge':
            expected['reported_energy_charge'].append('56.78')
        manifest.append({'id': name, 'file': name + '.png', 'kind': 'image', 'expected': expected,
                         'expected_rejected_fields': rejected, 'expected_conflicts': ['reported_energy_charge'] if name == 'conflicting-charge' else [],
                         'synthetic_only': True, 'rotation_degrees': rotation})
    pdf.save()
    subprocess.run(['pdftoppm', '-r', '150', '-png', str(document), str(DEST / 'page')], check=True, timeout=60)
    for index, item in enumerate(manifest, 1):
        generated = DEST / f'page-{index}.png'
        generated.rename(DEST / item['file'])
        item['sha256'] = hashlib.sha256((DEST / item['file']).read_bytes()).hexdigest()
        item['pixel_size'] = [1275, 1275]
    reader = PdfReader(document)
    writer = PdfWriter()
    writer.add_page(reader.pages[0]); writer.add_page(reader.pages[0])
    repeated = DEST / 'repeated-synthetic-pages.pdf'
    with repeated.open('xb') as handle:
        writer.write(handle)
    manifest.append({'id': 'repeated-pages', 'file': repeated.name, 'kind': 'pdf',
                     'expected': {key: value * 2 for key, value in VALUES.items()},
                     'expected_rejected_fields': [], 'expected_conflicts': [], 'synthetic_only': True,
                     'sha256': hashlib.sha256(repeated.read_bytes()).hexdigest()})
    with (DEST / 'manifest.json').open('x', encoding='utf-8', newline='\n') as handle:
        json.dump({'version': 1, 'synthetic_only': True, 'cases': manifest}, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'synthetic_cases': len(manifest), 'pdfs': 2, 'images': 8}))

if __name__ == '__main__':
    main()
