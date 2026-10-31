"""Frozen fractional-income counterexamples; all household data is synthetic."""
from datetime import date, timedelta
import math
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
from assistance_review import compare_assistance_candidate


class AssistanceIncomeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.rules = core.assistance_data()
        self.as_of = date.fromisoformat(self.rules["effective_from"])

    def screen(self, size, income, **kwargs):
        return core._screen_assistance_snapshot(
            self.rules, size, income, as_of=self.as_of, **kwargs)

    def assert_boundary_review(self, result, income, care_limit):
        self.assertEqual(result["status"], "screened")
        self.assertEqual(result["gross_annual_household_income"], income)
        self.assertEqual(result["care"]["status"], "likely_not_eligible_by_income")
        self.assertEqual(result["fera"]["status"], "needs_official_confirmation")
        self.assertEqual(result["fera"]["reason_code"], "FRACTIONAL_INCOME_BOUNDARY")
        self.assertEqual(result["fera"]["income_lower_bound"], care_limit + 1)
        self.assertEqual(result["fera"]["rounding_policy"], "unverified")
        gates = {gate["id"] for gate in result["human_gates"]}
        self.assertIn("INCOME_BOUNDARY_CONFIRMATION", gates)
        self.assertNotIn("ASSISTANCE_APPLICATION", gates)

    def test_gap_is_reviewable_for_each_supported_household_progression(self):
        for size in (1, 2, 3, 8, 9, 12):
            limit = core._income_limit(self.rules["care_income_upper_limit"], size)
            for fraction in (.01, .50, .99):
                income = limit + fraction
                with self.subTest(size=size, fraction=fraction):
                    self.assert_boundary_review(self.screen(size, income), income, limit)

    def test_subcent_and_adjacent_float_inputs_are_not_silently_rounded(self):
        limit = core._income_limit(self.rules["care_income_upper_limit"], 2)
        for income in (limit + .0001, math.nextafter(float(limit), math.inf),
                       math.nextafter(float(limit + 1), -math.inf)):
            with self.subTest(income=income):
                self.assert_boundary_review(self.screen(2, income), income, limit)

    def test_confirmed_table_edges_keep_existing_screening_outcomes(self):
        for size in (1, 3, 8, 9, 12):
            care = core._income_limit(self.rules["care_income_upper_limit"], size)
            fera = core._income_limit(self.rules["fera_income_upper_limit"], size)
            for income in (care - .01, care):
                with self.subTest(size=size, income=income):
                    result = self.screen(size, income)
                    self.assertEqual(result["care"]["status"], "likely_eligible")
                    self.assertEqual(result["fera"]["status"], "not_primary_path")
            for income in (care + 1, care + 1.01, fera - .01, fera):
                with self.subTest(size=size, income=income):
                    result = self.screen(size, income)
                    self.assertEqual(result["fera"]["status"], "likely_eligible")
                    self.assertNotIn("INCOME_BOUNDARY_CONFIRMATION", {g["id"] for g in result["human_gates"]})
            self.assertEqual(self.screen(size, fera + .01)["fera"]["status"], "likely_not_eligible_by_income")

    def test_categorical_eligibility_remains_an_independent_path(self):
        limit = core._income_limit(self.rules["care_income_upper_limit"], 3)
        result = self.screen(3, limit + .5, enrolled_public_programs=["SNAP"])
        self.assertEqual(result["care"]["status"], "likely_eligible")
        self.assertEqual(result["care"]["basis"], "categorical_program")
        self.assertEqual(result["fera"]["status"], "not_primary_path")
        self.assertNotIn("INCOME_BOUNDARY_CONFIRMATION", {g["id"] for g in result["human_gates"]})

    def test_medical_need_stays_separate_from_income_uncertainty(self):
        limit = core._income_limit(self.rules["care_income_upper_limit"], 1)
        result = self.screen(1, limit + .5, medical_baseline_need=True)
        self.assert_boundary_review(result, limit + .5, limit)
        self.assertEqual(result["medical_baseline"]["income_test"], "not_applicable")
        self.assertIn("MEDICAL_CERTIFICATION", {g["id"] for g in result["human_gates"]})

    def test_stale_rules_add_their_own_gate_without_erasing_boundary_review(self):
        limit = core._income_limit(self.rules["care_income_upper_limit"], 1)
        self.as_of = date.fromisoformat(self.rules["verified_on"]) + timedelta(days=46)
        result = self.screen(1, limit + .5)
        self.assert_boundary_review(result, limit + .5, limit)
        self.assertTrue(result["rules_freshness"]["verification_overdue"])
        self.assertIn("OFFICIAL_RATE_CONFIRMATION", {g["id"] for g in result["human_gates"]})

    def test_missing_income_and_expired_rules_are_not_invented(self):
        self.assertEqual(self.screen(1, None)["fera"]["status"], "needs_information")
        self.as_of = date.fromisoformat(self.rules["effective_to"]) + timedelta(days=1)
        result = self.screen(1, 43280.5)
        self.assertEqual(result["status"], "rules_outside_effective_window")
        self.assertEqual(result["fera"]["status"], "not_screened")

    def test_candidate_comparison_contains_fractional_old_and_new_boundaries(self):
        proposed = core.assistance_data()
        for name in ("care_income_upper_limit", "fera_income_upper_limit"):
            for key in proposed[name]:
                proposed[name][key] += 100
        result = compare_assistance_candidate(proposed)
        rows = result["screening_scenarios"]
        for size in (1, 2, 3, 8, 9, 12):
            for snapshot in (self.rules, proposed):
                care = core._income_limit(snapshot["care_income_upper_limit"], size)
                fera = core._income_limit(snapshot["fera_income_upper_limit"], size)
                for income in (care - .01, care + .01, care + .5, care + .99, fera - .01, fera + .01):
                    with self.subTest(size=size, income=income):
                        self.assertTrue(any(row["as_of"] == self.rules["effective_from"] and row["request"] == {
                            "household_size": size, "gross_annual_household_income": income} for row in rows))
        old_limit = core._income_limit(self.rules["care_income_upper_limit"], 1)
        row = next(row for row in rows if row["as_of"] == self.rules["effective_from"] and row["request"] == {
            "household_size": 1, "gross_annual_household_income": old_limit + .5})
        self.assertEqual(row["old"]["fera"]["status"], "needs_official_confirmation")
        self.assertEqual(row["candidate"]["care"]["status"], "likely_eligible")
        self.assertIn("INCOME_BOUNDARY_CONFIRMATION", row["old"]["human_gate_ids"])
        self.assertIsNone(result["approval"])
        self.assertFalse(result["automatic_activation"])
        self.assertEqual(core.assistance_data(), self.rules)


if __name__ == "__main__":
    unittest.main()
