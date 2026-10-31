"""Frozen tariff-review contracts; synthetic changes never authorize activation."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
from source_check import compare_candidate, validate_candidate

REQUEST = {"intervals": [{"start": "2026-07-06T17:00:00-07:00", "duration_minutes": 60, "kwh": 1}],
           "candidate_plans": ["E-TOU-D"]}


def changed_candidate():
    candidate = deepcopy(core.rate_data())
    candidate["plans"]["E-TOU-D"]["summer"]["peak"] = 0.87708
    return candidate


class TariffReviewIsolationTests(unittest.TestCase):
    def test_unapproved_review_cannot_change_a_concurrent_public_calculation(self):
        expected = core.compare_rate_plans(**REQUEST)
        entered, release = threading.Event(), threading.Event()
        real_load = core.load_usage
        calls = 0
        def load(*args, **kwargs):
            nonlocal calls
            if threading.current_thread().name.startswith("candidate-review"):
                calls += 1
                if calls == 2:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("Review checkpoint was not released")
            return real_load(*args, **kwargs)
        with patch.object(core, "load_usage", side_effect=load), ThreadPoolExecutor(max_workers=1, thread_name_prefix="candidate-review") as executor:
            future = executor.submit(compare_candidate, changed_candidate())
            try:
                self.assertTrue(entered.wait(5))
                observed = core.compare_rate_plans(**REQUEST)
            finally:
                release.set()
            review = future.result(timeout=5)
        self.assertEqual(observed, expected)
        self.assertIsNone(review["approval"])
        self.assertFalse(review["automatic_activation"])

    def test_review_freezes_candidate_before_calculation(self):
        candidate = changed_candidate()
        frozen = deepcopy(candidate)
        real_load = core.load_usage
        calls = 0
        def load(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                candidate["plans"]["E-TOU-D"]["summer"]["peak"] = 99.0
            return real_load(*args, **kwargs)
        with patch.object(core, "load_usage", side_effect=load):
            result = compare_candidate(candidate)
        summer = next(row for row in result["regression_scenarios"] if row["season"] == "summer")
        old = next(row for row in summer["old"] if row["plan"] == "E-TOU-D")
        new = next(row for row in summer["candidate"] if row["plan"] == "E-TOU-D")
        self.assertAlmostEqual(new["raw_energy_charge"] - old["raw_energy_charge"], 1.20, places=2)
        difference = next(row for row in result["differences"] if row["field"] == "plans.E-TOU-D.summer.peak")
        self.assertEqual(difference["new"], frozen["plans"]["E-TOU-D"]["summer"]["peak"])

    def test_returned_default_data_cannot_poison_the_cached_snapshot(self):
        for getter, key in ((core.rate_data, "plans"), (core.assistance_data, "care_income_upper_limit")):
            with self.subTest(key=key):
                expected = deepcopy(getter())
                exposed = getter()
                try:
                    exposed[key].clear()
                    self.assertEqual(getter(), expected)
                finally:
                    # Keep the failing baseline from corrupting other tests.
                    exposed.clear(); exposed.update(expected)

    def test_scope_rules_and_eligibility_lists_require_engine_review(self):
        baseline = deepcopy(core.rate_data())
        mutations = [lambda row: row.update(utility_code="OTHER"),
                     lambda row: row.update(service="CCA electricity"),
                     lambda row: row.update(schema_version="999"),
                     lambda row: row.update(limitations=[]),
                     lambda row: row["plans"]["E-ELEC"].update(qualifying_technologies=["unreviewed_technology"])]
        for mutation in mutations:
            candidate = deepcopy(baseline); mutation(candidate)
            with self.subTest(candidate=candidate.get("service")), self.assertRaises(ValueError):
                validate_candidate(candidate, baseline)

    def test_discounts_have_fraction_units_and_none_cannot_become_a_discount(self):
        baseline = deepcopy(core.rate_data())
        for program, value in (("care", 35), ("fera", 18), ("none", .01), ("care", 10**400)):
            candidate = deepcopy(baseline)
            candidate["assistance_volumetric_discount"][program] = value
            with self.subTest(program=program, value=str(value)[:20]), self.assertRaises(ValueError):
                validate_candidate(candidate, baseline)

    def test_source_identity_and_canonical_dates_are_not_free_text(self):
        baseline = deepcopy(core.rate_data())
        mutations = [lambda row: row["source"].update(workbook_sha256="not-a-hash"),
                     lambda row: row["source"].update(page_url="https://example.invalid/claimed-tariff"),
                     lambda row: row.update(verified_on="20261027"),
                     lambda row: row.update(effective_from="20260301")]
        for mutation in mutations:
            candidate = deepcopy(baseline); mutation(candidate)
            with self.subTest(source=candidate["source"]), self.assertRaises(ValueError):
                validate_candidate(candidate, baseline)

    def test_identity_review_and_failure_leave_defaults_unchanged(self):
        baseline = deepcopy(core.rate_data())
        same = compare_candidate(deepcopy(baseline))
        self.assertEqual(same["differences"], [])
        for row in same["regression_scenarios"]:
            self.assertEqual(row["old"], row["candidate"])
        with patch.object(core, "load_usage", side_effect=RuntimeError("SYNTHETIC_REVIEW_FAILURE")):
            with self.assertRaises(RuntimeError):
                compare_candidate(changed_candidate())
        self.assertEqual(core.rate_data(), baseline)

