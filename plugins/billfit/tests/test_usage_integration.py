from datetime import datetime, timedelta, timezone
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/billfit/scripts'
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
import billfit_usage as usage
import source_check


class UsageIntegrationTests(unittest.TestCase):
    def sample(self):
        return [{'start': '2026-07-06T17:00:00-07:00', 'kwh': 1, 'duration_minutes': 60}]

    def test_nonfinite_boolean_or_negative_bill_amount_cannot_validate(self):
        for amount in [float('inf'), float('-inf'), float('nan'), True, -1]:
            with self.subTest(amount=str(amount)):
                with self.assertRaises(core.BillFitError) as raised:
                    core.validate_bill(intervals=self.sample(), current_plan='E-TOU-D', reported_energy_charge=amount)
                self.assertEqual(raised.exception.code, 'INVALID_BILL_AMOUNT')

    def test_arithmetic_match_preserves_usage_quality_gate(self):
        result = core.compare_rate_plans(intervals=self.sample(), candidate_plans=['E-TOU-D'])['results'][0]
        validated = core.validate_bill(intervals=self.sample(), current_plan='E-TOU-D', reported_energy_charge=result['energy_charge_after_discount'])
        self.assertEqual(validated['status'], 'needs_review')
        self.assertEqual(validated['arithmetic_status'], 'matched')
        self.assertTrue(all(row['within_tolerance'] for row in validated['checks']))
        self.assertEqual(validated['validation_scope'], 'comparable_components_only')
        self.assertEqual(validated['usage_evidence_status'], 'needs_review')
        self.assertIn('USAGE_QUALITY_REVIEW', {row['id'] for row in validated['human_gates']})

    def test_previous_seasonal_five_plan_numbers_are_unchanged(self):
        original = json.loads((SCRIPTS.parent / 'data/verification/2026-10-27-regression.json').read_text(encoding='utf-8'))
        current = source_check.compare_candidate(core.rate_data())
        self.assertEqual(current['regression_scenarios'], original['regression_scenarios'])
        self.assertEqual(current['status'], 'REVIEW_REQUIRED')
        self.assertFalse(current['automatic_activation'])

    def test_complete_month_retains_reviewable_comparison(self):
        start = datetime.fromisoformat('2026-07-01T00:00:00-07:00')
        intervals = [{'start': (start + timedelta(hours=i)).isoformat(), 'kwh': 1, 'duration_minutes': 60} for i in range(28 * 24)]
        result = core.compare_rate_plans(intervals=intervals, candidate_plans=['E-TOU-D'])
        self.assertEqual(result['usage_summary']['quality'], 'good')
        self.assertEqual(result['recommendation']['status'], 'ranked_without_current_plan')
        self.assertNotIn('USAGE_QUALITY_REVIEW', {row['id'] for row in result['human_gates']})

    def test_splitting_preserves_elapsed_minutes_and_energy_across_dst(self):
        for start in ['2026-03-08T01:59:30-08:00', '2026-11-01T01:59:30-07:00', '2026-07-06T16:59:30-07:00']:
            intervals, _, _ = core.load_usage(intervals=[{'start': start, 'kwh': 17.3, 'duration_minutes': 120}])
            pieces = list(usage.split_interval(intervals[0]))
            self.assertAlmostEqual(sum(row[1] for row in pieces), 120)
            self.assertAlmostEqual(sum(row[2] for row in pieces), 17.3)
            instants = [row[0].astimezone(timezone.utc) for row in pieces]
            self.assertEqual(instants, sorted(set(instants)))

    def test_explicit_seconds_and_endpoint_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.csv'
            path.write_text('timestamp,end timestamp,usage,units,duration seconds\n2026-07-06T12:00:00-07:00,2026-07-06T12:15:00-07:00,250,Wh,900\n', encoding='utf-8')
            result = core.parse_usage_file(str(path))
            self.assertEqual(result['summary']['total_kwh'], .25)
            path.write_text(path.read_text(encoding='utf-8').replace(',900', ',1800'), encoding='utf-8')
            with self.assertRaises(core.BillFitError) as raised:
                core.parse_usage_file(str(path))
            self.assertEqual(raised.exception.code, 'CONFLICTING_INTERVAL_DURATION')

    def test_multiple_xml_usage_points_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.xml'
            path.write_text('<feed><ReadingType><uom>72</uom></ReadingType><UsagePoint/><UsagePoint/></feed>', encoding='utf-8')
            with self.assertRaises(core.BillFitError) as raised:
                core.parse_usage_file(str(path))
            self.assertEqual(raised.exception.code, 'MULTIPLE_USAGE_POINTS')

    def test_minimum_duration_and_aggregate_magnitude_are_bounded(self):
        for amount, minutes in [(1, 1e-100), (1e308, 60)]:
            with self.subTest(amount=amount, minutes=minutes), self.assertRaises(core.BillFitError):
                core.load_usage(intervals=[{'start': '2026-07-06T12:00:00-07:00', 'kwh': amount, 'duration_minutes': minutes}])

    def test_datetime_overflow_is_a_structured_error_and_short_final_interval_conserves_energy(self):
        with self.assertRaises(core.BillFitError) as raised:
            core.load_usage(intervals=[{'start': '9999-12-31T23:59:00+00:00', 'kwh': 1, 'duration_minutes': 60}])
        self.assertEqual(raised.exception.code, 'INVALID_INTERVAL_END')
        intervals, _, _ = core.load_usage(intervals=[{'start': '9999-12-31T23:59:00+00:00', 'kwh': 1, 'duration_minutes': .5}])
        self.assertEqual(sum(part[2] for part in usage.split_interval(intervals[0])), 1)

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK unavailable')
    def test_real_sdk_errors_and_recovery_preserve_usage_boundaries(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario(mode):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / 'mcp_server.py'), '--sdk'])
            async with Client(params, mode=mode) as client:
                bad = await client.call_tool('billfit_compare_rate_plans', {'intervals': self.sample() + [{**self.sample()[0], 'kwh': 2}], 'candidate_plans': ['E-TOU-D']})
                self.assertTrue(bad.is_error)
                self.assertEqual(bad.structured_content['error']['code'], 'CONFLICTING_DUPLICATE_INTERVAL')
                valid = await client.call_tool('billfit_compare_rate_plans', {'intervals': [
                    {'start': '2026-11-01T01:15:00-07:00', 'kwh': 1, 'duration_minutes': 15},
                    {'start': '2026-11-01T01:15:00-08:00', 'kwh': 1, 'duration_minutes': 15}], 'candidate_plans': ['E-TOU-D']})
                self.assertFalse(valid.is_error)
                self.assertEqual(valid.structured_content['usage_summary']['interval_count'], 2)
                self.assertEqual(valid.structured_content['recommendation']['status'], 'withheld_pending_usage_quality')
                invalid = await client.call_tool('billfit_validate_bill', {'intervals': self.sample(), 'current_plan': 'E-TOU-D', 'reported_energy_charge': -1})
                self.assertTrue(invalid.is_error)
                self.assertEqual(invalid.structured_content['error']['code'], 'INVALID_ARGUMENTS')
        for mode in ['2026-07-28', 'legacy']:
            asyncio.run(scenario(mode))


if __name__ == '__main__':
    unittest.main()
