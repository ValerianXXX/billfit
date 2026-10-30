"""Frozen input interoperability and unit conflicts, before the CSV repair."""
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


class CsvEnergyColumnTests(unittest.TestCase):
    fixture = SCRIPTS.parent / 'examples/synthetic-shared-kwh.csv'

    def parse(self, header, row):
        with tempfile.TemporaryDirectory(prefix='billfit-csv-') as directory:
            file = Path(directory) / 'synthetic.csv'
            file.write_text(header + '\n' + row + '\n', encoding='utf-8')
            return core.parse_usage_file(str(file))

    def expect_error(self, code, header, row):
        with self.assertRaises(core.BillFitError) as result:
            self.parse(header, row)
        self.assertEqual(result.exception.code, code)

    def test_frozen_shared_csv_deduplicates_and_totals(self):
        result = core.parse_usage_file(str(self.fixture))
        self.assertEqual(result['summary']['interval_count'], 4)
        self.assertEqual(result['summary']['total_kwh'], 2)
        self.assertEqual(result['summary']['elapsed_minutes'], 240)
        self.assertTrue(any('DUPLICATE_INTERVALS_REMOVED' in item for item in result['warnings']))
        self.assertFalse(any('ASSUMED_USAGE_UNIT' in item for item in result['warnings']))

    def test_short_sample_does_not_enable_switching(self):
        result = core.compare_rate_plans(usage_file=str(self.fixture), candidate_plans=['E-1'],
                                        baseline_territory='X', service_type='basic', qualifying_technologies=[])
        self.assertTrue(result['recommendation']['status'].startswith('withheld'))

    def test_normalized_kwh_header_is_explicit_energy(self):
        result = self.parse('timestamp,duration minutes,K W H', '2026-07-06T08:00:00-07:00,60,0.5')
        self.assertEqual(result['summary']['total_kwh'], .5)
        self.assertFalse(any('ASSUMED_USAGE_UNIT' in item for item in result['warnings']))

    def test_explicit_kwh_unit_alias_agrees(self):
        result = self.parse('timestamp,duration minutes,kwh,units', '2026-07-06T08:00:00-07:00,60,0.5,kilowatt-hours')
        self.assertEqual(result['summary']['total_kwh'], .5)

    def test_kwh_header_cannot_be_reinterpreted_as_wh(self):
        self.expect_error('CONFLICTING_USAGE_UNIT', 'timestamp,duration minutes,kwh,units',
                          '2026-07-06T08:00:00-07:00,60,500,Wh')

    def test_existing_usage_kwh_header_also_rejects_unit_conflict(self):
        self.expect_error('CONFLICTING_USAGE_UNIT', 'timestamp,duration minutes,usage kwh,units',
                          '2026-07-06T08:00:00-07:00,60,500,Wh')

    def test_two_energy_columns_need_explicit_selection(self):
        self.expect_error('AMBIGUOUS_CSV_ENERGY_COLUMNS', 'timestamp,duration minutes,usage,kwh',
                          '2026-07-06T08:00:00-07:00,60,1,2')

    def test_blank_first_energy_column_does_not_choose_second(self):
        self.expect_error('AMBIGUOUS_CSV_ENERGY_COLUMNS', 'timestamp,duration minutes,usage,value',
                          '2026-07-06T08:00:00-07:00,60,,2')

    def test_multiple_unit_columns_cannot_silently_select_one(self):
        self.expect_error('AMBIGUOUS_CSV_UNIT_COLUMNS', 'timestamp,duration minutes,usage,units,uom',
                          '2026-07-06T08:00:00-07:00,60,500,Wh,kWh')

    def test_empty_kwh_record_is_not_dropped(self):
        self.expect_error('MISSING_USAGE_VALUE', 'timestamp,duration minutes,kwh',
                          '2026-07-06T08:00:00-07:00,60,')

    def test_power_unit_is_rejected(self):
        self.expect_error('UNSUPPORTED_UOM', 'timestamp,duration minutes,kwh,units',
                          '2026-07-06T08:00:00-07:00,60,5,kW')

    def test_existing_explicit_wh_conversion_is_preserved(self):
        result = self.parse('timestamp,duration minutes,value,units', '2026-07-06T08:00:00-07:00,60,250,Wh')
        self.assertEqual(result['summary']['total_kwh'], .25)

    def test_unlabelled_usage_keeps_review_warning(self):
        result = self.parse('timestamp,duration minutes,usage', '2026-07-06T08:00:00-07:00,60,2')
        self.assertTrue(any('ASSUMED_USAGE_UNIT' in item for item in result['warnings']))

    def test_existing_usage_kwh_header_stays_supported(self):
        result = self.parse('timestamp,duration minutes,usage (kWh)', '2026-07-06T08:00:00-07:00,60,2')
        self.assertEqual(result['summary']['total_kwh'], 2)
        self.assertFalse(any('ASSUMED_USAGE_UNIT' in item for item in result['warnings']))


if __name__ == '__main__':
    unittest.main()
