"""Frozen public-input cases; no customer files or utility rounding assumption."""
import asyncio
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/usage-number-format-v1.json').read_text(encoding='utf-8'))
START = '2026-07-06T12:00:00-07:00'


def reading(kwh=1, minutes=60):
    return {'start': START, 'kwh': kwh, 'duration_minutes': minutes}


def csv_text(kwh=1, minutes=60):
    target = io.StringIO(newline='')
    writer = csv.writer(target)
    writer.writerow(['timestamp', 'duration minutes', 'kWh'])
    writer.writerow([START, minutes, kwh])
    return target.getvalue()


class UsageNumberFormatTests(unittest.TestCase):
    def parse(self, content, suffix='.csv'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('synthetic' + suffix)
            path.write_text(content, encoding='utf-8')
            before = path.read_bytes()
            try:
                return core.parse_usage_file(str(path))
            finally:
                self.assertEqual(path.read_bytes(), before)

    def rejected(self, code, operation):
        with self.assertRaises(core.BillFitError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn('IGNORED_SYNTHETIC_CELL', str(caught.exception))

    def test_inline_invalid_energy_is_not_repaired_into_another_number(self):
        for value in FIXTURE['invalid_energy']:
            with self.subTest(value=value):
                self.rejected('INVALID_USAGE_VALUE', lambda: core.load_usage(intervals=[reading(value)]))

    def test_inline_valid_formats_preserve_exact_interpreted_values(self):
        for case in FIXTURE['valid_energy']:
            with self.subTest(value=case['input']):
                values, _, _ = core.load_usage(intervals=[reading(case['input'])])
                self.assertEqual(values[0].kwh, case['kwh'])

    def test_explicit_duration_format_cannot_change_elapsed_time(self):
        for value in FIXTURE['invalid_duration']:
            with self.subTest(value=value):
                self.rejected('INVALID_INTERVAL_DURATION', lambda: core.load_usage(intervals=[reading(minutes=value)]))
        for case in FIXTURE['valid_duration']:
            with self.subTest(value=case['input']):
                values, _, _ = core.load_usage(intervals=[reading(minutes=case['input'])])
                self.assertEqual(values[0].duration_minutes, case['minutes'])

    def test_json_and_quoted_csv_apply_the_same_energy_contract(self):
        for value in FIXTURE['invalid_energy'][:14]:
            for suffix, content in [('.json', json.dumps({'intervals': [reading(value)]})),
                                    ('.csv', csv_text(value))]:
                with self.subTest(value=value, suffix=suffix):
                    self.rejected('INVALID_USAGE_VALUE', lambda: self.parse(content, suffix))
        for case in FIXTURE['valid_energy']:
            for suffix, content in [('.json', json.dumps({'intervals': [reading(case['input'])]})),
                                    ('.csv', csv_text(case['input']))]:
                with self.subTest(value=case['input'], suffix=suffix):
                    self.assertEqual(self.parse(content, suffix)['summary']['total_kwh'], case['kwh'])

    def test_csv_never_discards_surplus_cells_even_when_trailing_cell_is_empty(self):
        for row in FIXTURE['extra_csv_records']:
            with self.subTest(row=row):
                self.rejected('CSV_ROW_WIDTH_MISMATCH', lambda: self.parse('timestamp,duration minutes,kWh\n' + row + '\n'))

    def test_optional_missing_csv_cells_keep_existing_quality_gate(self):
        result = self.parse('timestamp,kWh,duration minutes\n' + START + ',1\n')
        self.assertEqual(result['summary']['total_kwh'], 1)
        self.assertTrue(any('INFERRED_INTERVAL_DURATION' in value for value in result['warnings']))

    def test_xml_energy_and_seconds_cannot_remove_punctuation(self):
        def xml(value='250', seconds='900'):
            return ('<feed><ReadingType><uom>72</uom><powerOfTenMultiplier>0</powerOfTenMultiplier></ReadingType>'
                    '<IntervalBlock><IntervalReading><timePeriod><start>1783350000</start><duration>' + seconds +
                    '</duration></timePeriod><value>' + value + '</value></IntervalReading></IntervalBlock></feed>')
        for value in ('1,23', '$250', '2_50', '1e-400'):
            with self.subTest(energy=value):
                self.rejected('INVALID_USAGE_VALUE', lambda: self.parse(xml(value), '.xml'))
        self.rejected('INVALID_INTERVAL_DURATION', lambda: self.parse(xml(seconds='9,00'), '.xml'))
        self.assertEqual(self.parse(xml(), '.xml')['summary']['total_kwh'], .25)

    def test_rejected_input_cannot_reach_comparison_or_bill_reconciliation(self):
        self.rejected('INVALID_USAGE_VALUE', lambda: core.compare_rate_plans(
            intervals=[reading('1,23')], candidate_plans=['E-TOU-D']))
        self.rejected('INVALID_USAGE_VALUE', lambda: core.validate_bill(
            intervals=[reading('1,23')], current_plan='E-TOU-D', reported_energy_charge=1))
        values, _, _ = core.load_usage(intervals=[reading('(1.25)')])
        self.assertEqual(values[0].kwh, -1.25)
        result = core.compare_rate_plans(intervals=[reading('(1.25)')], candidate_plans=['E-TOU-D'])
        self.assertEqual(result['results'][0]['error']['code'], 'UNSUPPORTED_NET_EXPORT')

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK unavailable')
    def test_actual_sdk_file_rejection_and_same_connection_recovery(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario(mode):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'synthetic.csv'
                path.write_text(csv_text('1,23'), encoding='utf-8')
                params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / 'mcp_server.py'), '--sdk'])
                async with Client(params, mode=mode) as client:
                    result = await client.call_tool('billfit_parse_usage_file', {'usage_file': str(path)})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content['error']['code'], 'INVALID_USAGE_VALUE')
                    path.write_text(csv_text('1,234.5'), encoding='utf-8')
                    result = await client.call_tool('billfit_parse_usage_file', {'usage_file': str(path)})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content['summary']['total_kwh'], 1234.5)
                    self.assertEqual(result.structured_content['summary']['quality'], 'limited')
        for mode in ['2026-07-28', 'legacy']:
            with self.subTest(mode=mode):
                asyncio.run(scenario(mode))


if __name__ == '__main__':
    unittest.main()
