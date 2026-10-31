"""Synthetic evidence and monetary-boundary contracts frozen before the repair."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


def hours(start="2026-07-01T00:00:00-07:00", count=31 * 24, kwh=1):
    instant = datetime.fromisoformat(start).astimezone(timezone.utc)
    return [{"start": (instant + timedelta(hours=i)).isoformat(), "duration_minutes": 60, "kwh": kwh}
            for i in range(count)]


JULY = {"start_date": "2026-07-01", "end_date_exclusive": "2026-08-01"}


class BillReconciliationTests(unittest.TestCase):
    def setUp(self):
        # Freeze observation time, not the tariff values or calculator output.
        original = core._freshness
        self.freshness = patch.object(core, "_freshness", side_effect=lambda r: original(r, date(2026, 10, 31)))
        self.freshness.start()
        self.addCleanup(self.freshness.stop)

    def matched(self, rows=None, **extra):
        rows = hours() if rows is None else rows
        calculated = core.compare_rate_plans(intervals=rows, candidate_plans=["E-TOU-D"])["results"][0]
        return core.validate_bill(intervals=rows, current_plan="E-TOU-D",
                                  reported_energy_charge=calculated["energy_charge_after_discount"], **extra)

    def test_two_dollar_tolerance_boundary_uses_decimal_cents(self):
        result = core.validate_bill(intervals=hours("2026-07-06T17:00:00-07:00", 1, 9.23),
                                    current_plan="E-TOU-D", reported_energy_charge=2.40)
        check = result["checks"][0]
        self.assertEqual(check["calculated"], 4.40)
        self.assertEqual(check["difference"], 2.00)
        self.assertTrue(check["within_tolerance"])
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertEqual(result["status"], "needs_review")

    def test_subcent_amounts_are_not_silently_rounded_to_bill_fields(self):
        for amount in (2.405, "2.405", 0.001, 10**400):
            with self.subTest(amount=str(amount)[:20]):
                with self.assertRaises(core.BillFitError) as caught:
                    core.validate_bill(intervals=hours(count=1), current_plan="E-TOU-D", reported_energy_charge=amount)
                self.assertEqual(caught.exception.code, "INVALID_BILL_AMOUNT")

    def test_one_hour_arithmetic_match_is_not_validated_bill_evidence(self):
        result = self.matched(hours(count=1))
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertIn("BILLING_PERIOD_REQUIRED", result["required_reviews"])
        self.assertIn("USAGE_QUALITY_REVIEW", {g["id"] for g in result["human_gates"]})

    def test_complete_month_without_bill_dates_still_needs_period_confirmation(self):
        result = self.matched()
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["required_reviews"], ["BILLING_PERIOD_REQUIRED"])

    def test_full_explicit_period_can_validate_only_comparable_components(self):
        result = self.matched(billing_period=JULY)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["validation_scope"], "comparable_components_only")
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertEqual(result["required_reviews"], [])
        self.assertEqual(result["billing_period"]["calendar_days"], 31)
        self.assertEqual(result["billing_period"]["missing_minutes"], 0)
        self.assertEqual(result["simulation"]["billing_days"], 31)

    def test_one_missing_hour_withholds_switch_savings_even_above_95_percent(self):
        rows = hours()
        del rows[200]
        result = core.compare_rate_plans(intervals=rows, current_plan="E-TOU-D", candidate_plans=["E-TOU-D", "E-TOU-C"], baseline_territory="T", service_type="basic")
        self.assertEqual(result["usage_summary"]["quality"], "good")
        self.assertEqual(result["usage_summary"]["gap_minutes"], 60)
        self.assertEqual(result["recommendation"]["status"], "withheld_pending_usage_quality")
        self.assertNotIn("estimated_annual_savings", result["recommendation"])

    def test_missing_edge_day_is_visible_against_declared_period(self):
        result = self.matched(hours()[24:], billing_period=JULY)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["billing_period"]["missing_minutes"], 1440)
        self.assertIn("INCOMPLETE_BILLING_PERIOD", result["required_reviews"])
        self.assertEqual(result["simulation"]["billing_days"], 31)
        self.assertEqual(result["simulation"]["base_services_charge"], 24.39)

    def test_extra_usage_is_not_silently_clipped_to_the_bill_period(self):
        result = self.matched(hours(count=31 * 24 + 1), billing_period=JULY)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["billing_period"]["outside_interval_count"], 1)
        self.assertIn("USAGE_OUTSIDE_BILLING_PERIOD", result["required_reviews"])
        self.assertEqual(result["simulation"]["usage_kwh"], 745)

    def test_inferred_duration_prevents_validation_even_with_full_coverage(self):
        rows = hours()
        for row in rows:
            del row["duration_minutes"]
        result = self.matched(rows, billing_period=JULY)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("USAGE_ASSUMPTIONS_REQUIRE_REVIEW", result["required_reviews"])

    def test_stale_snapshot_drops_savings_fields_instead_of_only_relabeling(self):
        rates = core.rate_data()
        rates["verified_on"] = "2025-01-01"
        result = core._compare_rate_snapshot(rates, intervals=hours(), current_plan="E-TOU-D", candidate_plans=["E-TOU-D"])
        self.assertEqual(result["recommendation"]["status"], "withheld_pending_rate_verification")
        self.assertNotIn("estimated_annual_savings", result["recommendation"])
        self.assertNotIn("estimated_savings_percent", result["recommendation"])

    def test_stale_arithmetic_match_is_not_validated(self):
        rates = core.rate_data()
        rates["verified_on"] = "2025-01-01"
        with patch.object(core, "rate_data", return_value=rates):
            result = self.matched(billing_period=JULY)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertIn("RATE_VERIFICATION_REQUIRED", result["required_reviews"])

    def test_new_snapshot_cannot_validate_usage_before_its_effective_date(self):
        period = {"start_date": "2026-02-28", "end_date_exclusive": "2026-03-02"}
        result = self.matched(hours("2026-02-28T00:00:00-08:00", 48), billing_period=period)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("RATE_PERIOD_NOT_COVERED", result["required_reviews"])

    def test_malformed_or_unbounded_period_is_a_structured_error(self):
        for period in ({}, {**JULY, "approved": True}, {**JULY, "start_date": "20260701"},
                       {**JULY, "end_date_exclusive": "2026-07-01"},
                       {**JULY, "end_date_exclusive": "2030-01-01"},
                       {**JULY, "start_date": True}, "not a period"):
            with self.subTest(period=period):
                with self.assertRaises(core.BillFitError) as caught:
                    self.matched(hours(count=1), billing_period=period)
                self.assertEqual(caught.exception.code, "INVALID_BILLING_PERIOD")

    def test_no_amount_keeps_period_and_source_diagnostics(self):
        result = core.validate_bill(intervals=hours(), current_plan="E-TOU-D", billing_period=JULY)
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["arithmetic_status"], "not_checked")
        self.assertEqual(result["billing_period"]["calendar_days"], 31)
        self.assertIn("source", result["rate_snapshot"])

    def test_dst_calendar_days_are_distinct_from_elapsed_hours(self):
        for start, count, period in (
            ("2026-03-08T00:00:00-08:00", 23, {"start_date": "2026-03-08", "end_date_exclusive": "2026-03-09"}),
            ("2026-11-01T00:00:00-07:00", 25, {"start_date": "2026-11-01", "end_date_exclusive": "2026-11-02"}),
        ):
            with self.subTest(start=start):
                result = self.matched(hours(start, count), billing_period=period)
                self.assertEqual(result["billing_period"]["calendar_days"], 1)
                self.assertEqual(result["billing_period"]["expected_minutes"], count * 60)
                self.assertEqual(result["billing_period"]["missing_minutes"], 0)
                self.assertEqual(result["simulation"]["base_services_charge"], .79)


if __name__ == "__main__":
    unittest.main()
