"""Frozen synthetic public-boundary tests; no real bill or OCR process."""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
from bill_input import extract_bill_fields, extract_spans
from billfit_errors import BillFitError

HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
PAGE = '1\t1\t0\t0\t0\t0\t0\t0\t1300\t620\t-1\t'
WORDS = ['5\t1\t1\t1\t1\t1\t50\t100\t80\t20\t95\tEnergy',
         '5\t1\t1\t1\t1\t2\t140\t100\t90\t20\t96\tCharges',
         '5\t1\t1\t1\t1\t3\t240\t100\t80\t20\t32\t$12.34']
TSV = '\n'.join([HEADER, PAGE, *WORDS]) + '\n'

class FakeProcess:
    def __init__(self, command, *, output=TSV, returncode=0, started=None, **kwargs):
        self.args = command
        self.returncode = returncode
        self.output = output
        self.stdout = io.BytesIO(output.encode())
        self.stderr = io.BytesIO(b'SYNTHETIC_PRIVATE_ERROR_DO_NOT_RETURN')
        self.text = kwargs.get('text', False) or bool(kwargs.get('encoding'))
        if started:
            started(command)
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def communicate(self, *_args, **_kwargs):
        return (self.output, 'SYNTHETIC_PRIVATE_ERROR_DO_NOT_RETURN') if self.text else (self.output.encode(), b'error')
    def wait(self, timeout=None): return self.returncode
    def poll(self): return self.returncode
    def kill(self): self.returncode = -1

class BillInputNumericEvidenceTests(unittest.TestCase):
    def extract(self, text):
        return extract_spans([{'page': 1, 'line': 1, 'text': text}], 'synthetic-sha', 'CONTRACT_TEXT')

    def test_valid_grouped_numbers_preserve_exact_source_quote(self):
        text = 'Energy Charges $1,234.56; Base Services Charge $0.79; Usage 1,234.5 kWh'
        result = self.extract(text)
        self.assertEqual({x['field']: x['value'] for x in result['candidates']}, {
            'reported_energy_charge': '1234.56', 'reported_base_services_charge': '0.79', 'total_kwh': '1234.5'})
        for row in result['candidates']:
            source = row['source']
            self.assertEqual(text[source['start']:source['end']], source['quote'])
            self.assertEqual(row['status'], 'NEEDS_USER_CONFIRMATION')

    def test_malformed_comma_groups_are_not_repaired_to_different_amounts(self):
        for text in ['Energy Charges $12,34.56', 'Energy Charges $,123.45', 'Base Services Charge $1,,234.56', 'Usage 25,5 kWh']:
            with self.subTest(text=text):
                result = self.extract(text)
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['unresolved_fields'])

    def test_amount_prefix_does_not_hide_extra_decimal_or_digit_suffix(self):
        for text in ['Energy Charges $12.34.56', 'Energy Charges $12.34,56', 'Base Services Charge $0.79/2']:
            with self.subTest(text=text):
                self.assertEqual(self.extract(text)['candidates'], [])

    def test_explicit_credits_and_ranges_are_not_positive_charge_candidates(self):
        for text in ['Energy Charges $12.34 CR', 'Energy Charges $12.34 credit', 'Energy Charges $12.34 - $20.00',
                     'Base Services Charge $0.79 to $1.00', 'Energy Charges -$12.34', 'Energy Charges ($12.34)']:
            with self.subTest(text=text):
                self.assertEqual(self.extract(text)['candidates'], [])

    def test_plan_prefix_cannot_hide_an_unsupported_plan_suffix(self):
        self.assertEqual(self.extract('Rate Schedule: E-TOU-D-NEM')['candidates'], [])

    def test_repeated_fields_keep_each_page_and_are_never_added(self):
        result = extract_spans([{'page': page, 'line': 1, 'text': 'Energy Charges $12.34'} for page in (1, 2)], 'synthetic', 'TEST')
        self.assertEqual([x['value'] for x in result['candidates']], ['12.34', '12.34'])
        self.assertEqual([x['source']['page'] for x in result['candidates']], [1, 2])
        self.assertFalse(result['automatic_calculation'])
        self.assertFalse(result['automatic_confirmation'])

class BillInputOcrEvidenceTests(unittest.TestCase):
    def run_ocr(self, text=TSV, *, started=None, returncode=0):
        with tempfile.TemporaryDirectory(prefix='billfit-input-contract-') as directory:
            path = Path(directory) / 'synthetic.png'
            raw = b'SYNTHETIC_IMAGE_CONTRACT_BYTES'
            path.write_bytes(raw)
            seen = []
            def capture(command):
                seen.append((Path(command[1]), Path(command[1]).read_bytes()))
                if started:
                    started(path)
            def process(command, **kwargs):
                return FakeProcess(command, output=text, returncode=returncode, started=capture, **kwargs)
            with patch.dict('os.environ', {'BILLFIT_TESSERACT_PATH': sys.executable}), patch('subprocess.Popen', side_effect=process):
                result = extract_bill_fields(str(path))
            return result, raw, path, seen

    def test_ocr_reads_an_owned_snapshot_and_binds_its_exact_bytes(self):
        result, raw, original, seen = self.run_ocr()
        self.assertNotEqual(seen[0][0], original)
        self.assertEqual(seen[0][1], raw)
        self.assertFalse(seen[0][0].exists())
        self.assertEqual(result['candidates'][0]['source']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_source_replacement_during_ocr_cannot_relabel_extracted_evidence(self):
        with self.assertRaises(BillFitError) as caught:
            self.run_ocr(started=lambda path: path.write_bytes(b'CHANGED_SOURCE'))
        self.assertEqual(caught.exception.code, 'BILL_SOURCE_CHANGED')

    def test_low_word_confidence_is_visible_and_not_a_probability(self):
        result, *_ = self.run_ocr()
        row = result['candidates'][0]
        self.assertEqual(row['source']['ocr_confidence']['minimum'], 32)
        self.assertFalse(row['source']['ocr_confidence']['calibrated'])
        self.assertIn('LOW_OCR_CONFIDENCE', row['quality_flags'])
        self.assertEqual(row['status'], 'NEEDS_USER_CONFIRMATION')

    def test_words_outside_declared_page_are_rejected(self):
        for left, width in [(-1, 80), (1290, 80), (50, 0)]:
            rows = [*WORDS]
            pieces = rows[-1].split('\t'); pieces[6] = str(left); pieces[8] = str(width); rows[-1] = '\t'.join(pieces)
            with self.subTest(left=left, width=width), self.assertRaises(BillFitError) as caught:
                self.run_ocr('\n'.join([HEADER, PAGE, *rows]) + '\n')
            self.assertEqual(caught.exception.code, 'OCR_OUTPUT_INVALID')

    def test_duplicate_word_identity_with_conflicting_text_is_rejected(self):
        with self.assertRaises(BillFitError) as caught:
            self.run_ocr(TSV + WORDS[-1].replace('$12.34', '$99.99') + '\n')
        self.assertEqual(caught.exception.code, 'OCR_OUTPUT_INVALID')

    def test_repeated_identical_ocr_word_is_not_duplicated(self):
        result, *_ = self.run_ocr(TSV + WORDS[-1] + '\n')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['source']['quote'], 'Energy Charges $12.34')

    def test_nonfinite_or_out_of_range_confidence_is_rejected(self):
        for value in ('nan', '101', '-2'):
            with self.subTest(value=value), self.assertRaises(BillFitError) as caught:
                self.run_ocr(TSV.replace('\t32\t', '\t' + value + '\t'))
            self.assertEqual(caught.exception.code, 'OCR_OUTPUT_INVALID')

    def test_malformed_tsv_is_not_reported_as_an_empty_readable_bill(self):
        for text in ('not a TSV\n', TSV.replace('conf\ttext', 'conf\tconf'), TSV.replace('\t32\t', '\t32\textra\t')):
            with self.subTest(text=text[:30]), self.assertRaises(BillFitError) as caught:
                self.run_ocr(text)
            self.assertEqual(caught.exception.code, 'OCR_OUTPUT_INVALID')

    def test_process_failure_is_a_fixed_redacted_domain_error(self):
        with self.assertRaises(BillFitError) as caught:
            self.run_ocr(returncode=1)
        self.assertEqual(caught.exception.code, 'LOCAL_OCR_FAILED')
        self.assertNotIn('SYNTHETIC_PRIVATE', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
