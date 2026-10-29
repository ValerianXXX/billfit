"""Fixed synthetic correctness contracts, recorded before the interval refactor."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


def reading(start='2026-07-06T12:00:00-07:00', kwh=1, minutes=60):
    return {'start': start, 'kwh': kwh, 'duration_minutes': minutes}


class IntervalBoundaryTests(unittest.TestCase):
    def parse(self, content, suffix='.csv'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('synthetic' + suffix)
            path.write_text(content, encoding='utf-8')
            return core.parse_usage_file(str(path))

    def parse_intervals(self, values):
        return self.parse(json.dumps({'intervals': values}), '.json')

    def expect_error(self, code, operation):
        with self.assertRaises(core.BillFitError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def xml(self, readings='', types=None):
        types = types or '<ReadingType><powerOfTenMultiplier>0</powerOfTenMultiplier><uom>72</uom></ReadingType>'
        return '<feed>' + types + '<IntervalBlock>' + readings + '</IntervalBlock></feed>'

    def xml_reading(self, value='250', duration='900'):
        duration_tag = '' if duration is None else '<duration>' + duration + '</duration>'
        return '<IntervalReading><timePeriod><start>1783346400</start>' + duration_tag + '</timePeriod><value>' + value + '</value></IntervalReading>'

    def test_identical_duplicate_keeps_one_usage_value_and_warning(self):
        result = self.parse_intervals([reading(), reading()])
        self.assertEqual(result['summary']['interval_count'], 1)
        self.assertEqual(result['summary']['total_kwh'], 1)
        self.assertTrue(any('DUPLICATE_INTERVALS_REMOVED' in text for text in result['warnings']))

    def test_conflicting_duplicate_is_rejected(self):
        self.expect_error('CONFLICTING_DUPLICATE_INTERVAL', lambda: self.parse_intervals([reading(), reading(kwh=2)]))

    def test_overlapping_intervals_are_rejected(self):
        self.expect_error('OVERLAPPING_INTERVALS', lambda: self.parse_intervals([reading(), reading('2026-07-06T12:30:00-07:00')]))

    def test_fall_back_explicit_offsets_remain_distinct(self):
        result = self.parse_intervals([reading('2026-11-01T01:15:00-07:00', minutes=15), reading('2026-11-01T01:15:00-08:00', minutes=15)])
        self.assertEqual(result['summary']['interval_count'], 2)
        self.assertEqual(result['summary']['total_kwh'], 2)
        self.assertEqual([x['start'][-6:] for x in result['preview']], ['-07:00', '-08:00'])

    def test_ambiguous_local_time_needs_explicit_offset(self):
        self.expect_error('AMBIGUOUS_LOCAL_TIME', lambda: self.parse_intervals([reading('2026-11-01T01:15:00')]))

    def test_nonexistent_local_time_is_rejected(self):
        self.expect_error('NONEXISTENT_LOCAL_TIME', lambda: self.parse_intervals([reading('2026-03-08T02:15:00')]))

    def test_spring_duration_is_elapsed_time(self):
        result = self.parse_intervals([reading('2026-03-08T01:45:00-08:00', minutes=30)])
        self.assertEqual(result['summary']['end'], '2026-03-08T03:15:00-07:00')
        self.assertEqual(result['summary']['coverage_ratio'], 1)

    def test_fall_duration_is_elapsed_time(self):
        result = self.parse_intervals([reading('2026-11-01T01:45:00-07:00', minutes=30)])
        self.assertEqual(result['summary']['end'], '2026-11-01T01:15:00-08:00')
        self.assertEqual(result['summary']['coverage_ratio'], 1)

    def test_fall_coverage_counts_both_repeated_hours(self):
        values = [reading('2026-11-01T00:00:00-07:00'), reading('2026-11-01T01:00:00-07:00'), reading('2026-11-01T01:00:00-08:00'), reading('2026-11-01T02:00:00-08:00')]
        result = self.parse_intervals(values)
        self.assertEqual(result['summary']['interval_count'], 4)
        self.assertEqual(result['summary']['span_days'], round(4 / 24, 3))
        self.assertEqual(result['summary']['coverage_ratio'], 1)

    def test_tariff_boundary_splits_at_clock_boundary(self):
        result = core.compare_rate_plans(intervals=[reading('2026-07-06T16:59:00-07:00', kwh=2, minutes=2)], candidate_plans=['E-TOU-D'])
        periods = result['results'][0]['usage_by_period_kwh']
        self.assertEqual(periods, {'summer_off_peak': 1, 'summer_peak': 1})

    def day(self, start, hours):
        instant = datetime.fromisoformat(start).astimezone(timezone.utc)
        return [reading((instant + timedelta(hours=i)).isoformat(), kwh=1) for i in range(hours)]

    def test_spring_full_calendar_day_keeps_full_baseline_allowance(self):
        result = core.compare_rate_plans(intervals=self.day('2026-03-08T00:00:00-08:00', 23), candidate_plans=['E-1'], baseline_territory='T', service_type='basic')
        self.assertEqual(result['results'][0]['baseline_kwh'], core.rate_data()['baseline_daily_kwh']['T']['basic']['winter'])
        self.assertEqual(result['results'][0]['usage_kwh'], 23)

    def test_fall_full_calendar_day_preserves_25_readings(self):
        result = core.compare_rate_plans(intervals=self.day('2026-11-01T00:00:00-07:00', 25), candidate_plans=['E-1'], baseline_territory='T', service_type='basic')
        self.assertEqual(result['usage_summary']['interval_count'], 25)
        self.assertEqual(result['results'][0]['baseline_kwh'], core.rate_data()['baseline_daily_kwh']['T']['basic']['winter'])

    def test_explicit_csv_minutes_are_never_guessed_as_seconds(self):
        result = self.parse('timestamp,usage,units,duration minutes\n2026-07-06T12:00:00-07:00,1,kWh,600\n')
        self.assertEqual(result['preview'][0]['duration_minutes'], 600)

    def test_missing_duration_is_disclosed(self):
        item = reading()
        del item['duration_minutes']
        result = self.parse_intervals([item])
        self.assertTrue(any('INFERRED_INTERVAL_DURATION' in text for text in result['warnings']))

    def test_explicit_zero_duration_is_rejected(self):
        self.expect_error('INVALID_INTERVAL_DURATION', lambda: self.parse_intervals([reading(minutes=0)]))

    def test_explicit_negative_duration_is_rejected(self):
        self.expect_error('INVALID_INTERVAL_DURATION', lambda: self.parse_intervals([reading(minutes=-15)]))

    def test_nonfinite_usage_is_rejected(self):
        self.expect_error('INVALID_USAGE_VALUE', lambda: self.parse_intervals([reading(kwh=float('nan'))]))

    def test_infinite_usage_is_rejected(self):
        self.expect_error('INVALID_USAGE_VALUE', lambda: self.parse_intervals([reading(kwh=float('inf'))]))

    def test_boolean_usage_is_rejected(self):
        self.expect_error('INVALID_USAGE_VALUE', lambda: self.parse_intervals([reading(kwh=True)]))

    def test_nonfinite_duration_is_rejected(self):
        self.expect_error('INVALID_INTERVAL_DURATION', lambda: self.parse_intervals([reading(minutes=float('inf'))]))

    def test_unknown_csv_units_are_rejected(self):
        self.expect_error('UNSUPPORTED_UOM', lambda: self.parse('timestamp,usage,units,duration minutes\n2026-07-06T12:00:00-07:00,250,W,15\n'))

    def test_wh_csv_is_converted_to_kwh(self):
        result = self.parse('timestamp,usage,units,duration minutes\n2026-07-06T12:00:00-07:00,250,Wh,15\n')
        self.assertEqual(result['summary']['total_kwh'], 0.25)

    def test_missing_csv_timestamp_cannot_silently_drop_usage(self):
        self.expect_error('MISSING_INTERVAL_TIMESTAMP', lambda: self.parse('timestamp,usage,units,duration minutes\n2026-07-06T12:00:00-07:00,1,kWh,15\n,2,kWh,15\n'))

    def test_multiple_xml_reading_types_cannot_share_first_unit(self):
        types = '<ReadingType><uom>72</uom></ReadingType><ReadingType><uom>kWh</uom></ReadingType>'
        self.expect_error('AMBIGUOUS_ESPI_READING_TYPE', lambda: self.parse(self.xml(self.xml_reading(), types), '.xml'))

    def test_missing_xml_duration_is_rejected(self):
        self.expect_error('MISSING_ESPI_INTERVAL_FIELD', lambda: self.parse(self.xml(self.xml_reading(duration=None)), '.xml'))

    def test_invalid_xml_multiplier_is_not_silently_zero(self):
        types = '<ReadingType><powerOfTenMultiplier>bad</powerOfTenMultiplier><uom>72</uom></ReadingType>'
        self.expect_error('INVALID_ESPI_MULTIPLIER', lambda: self.parse(self.xml(self.xml_reading(), types), '.xml'))

    def test_limited_usage_withholds_switch_savings(self):
        result = core.compare_rate_plans(intervals=[reading('2026-07-06T18:00:00-07:00', kwh=30)], candidate_plans=['E-TOU-C', 'E-TOU-D'], current_plan='E-TOU-C', baseline_territory='T', service_type='basic')
        self.assertEqual(result['recommendation']['status'], 'withheld_pending_usage_quality')
        self.assertNotIn('estimated_annual_savings', result['recommendation'])

    def test_duplicate_csv_headers_are_rejected(self):
        self.expect_error('AMBIGUOUS_CSV_HEADER', lambda: self.parse('timestamp,usage,usage,units\n2026-07-06T12:00:00-07:00,1,2,kWh\n'))


if __name__ == '__main__':
    unittest.main()
