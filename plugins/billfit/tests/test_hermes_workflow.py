"""Offline checks for the opt-in live evaluator; these do not call a model."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("workflow_probe", ROOT / "scripts/probe_hermes_workflow.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class WorkflowProbeTests(unittest.TestCase):
    def test_fixed_original_synthetic_inputs_are_hash_locked(self):
        self.assertEqual(probe.canonical_sha(probe.BILL), probe.BILL_SHA)
        self.assertEqual(probe.canonical_sha(probe.USAGE), probe.USAGE_SHA_LF)

    def test_no_unprovided_files_or_fabricated_intervals(self):
        paths = {"synthetic-workflow-bill.pdf": "fixed/bill.pdf", "demo_usage.csv": "fixed/usage.csv"}
        for name, arguments, phase in [
            ("billfit_extract_bill_fields", {"bill_file": "../real.pdf"}, 1),
            ("billfit_compare_rate_plans", {"intervals": [{"kwh": 25.5}]}, 2),
            ("billfit_parse_usage_file", {"usage_file": "demo_usage.csv"}, 1),
            ("billfit_screen_assistance", {"household_size": 2, "gross_annual_household_income": 0}, 1),
            ("billfit_screen_assistance", {"household_size": 2, "gross_annual_household_income": 40000, "medical_baseline_need": True}, 1),
        ]:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(ValueError):
                probe.bounded_arguments(name, arguments, phase, paths)
        original = {"bill_file": "synthetic-workflow-bill.pdf"}
        self.assertEqual(probe.bounded_arguments("billfit_extract_bill_fields", original, 1, paths), {"bill_file": "fixed/bill.pdf"})
        self.assertEqual(original["bill_file"], "synthetic-workflow-bill.pdf")

    def test_empty_malformed_and_rejected_results_cannot_pass(self):
        for phase in (1, 2):
            checks = probe.assess(phase, {}, {"fields": None, "missing_inputs": None, "human_gates": [{}]}, [], [])
            self.assertFalse(all(checks.values()))
            self.assertFalse(checks["tool_calls_succeeded"])
            self.assertFalse(checks["required_tools_selected"])
            self.assertFalse(probe.assess(phase, {}, {}, [], ["rejected"])["tool_boundary_respected"])

    def test_final_fields_must_preserve_exact_unconfirmed_source(self):
        candidates = [{"field": key, "value": value, "status": "NEEDS_USER_CONFIRMATION",
                       "source": {"sha256": probe.BILL_SHA, "page": 1, "line": i, "quote": f"fixture {key}"}}
                      for i, (key, value) in enumerate(probe.EXPECTED_FIELDS.items(), 1)]
        captured = {"billfit_get_supported_scope": {},
                    "billfit_extract_bill_fields": {"candidates": candidates, "automatic_confirmation": False, "automatic_calculation": False},
                    "billfit_screen_assistance": {"care": {"status": "likely_eligible", "income_upper_limit": 43280}, "source": {"url": "https://www.cpuc.ca.gov/care/"}}}
        answer = {"fields": copy.deepcopy(candidates), "care_status": "likely_eligible", "care_income_limit": 43280,
                  "assistance_source_url": "https://www.cpuc.ca.gov/care/", "missing_inputs": ["INTERVAL_USAGE", "BILL_FIELD_CONFIRMATION"],
                  "human_gates": ["ASSISTANCE_APPLICATION"], "switch_recommended": False, "application_submitted": False}
        trace = [{"is_error": False}]
        self.assertTrue(all(probe.assess(1, captured, answer, trace, []).values()))
        for field, value in (("status", "CONFIRMED"), ("value", "fabricated"), ("source", {"page": 99})):
            changed = copy.deepcopy(answer)
            changed["fields"][0][field] = value
            self.assertFalse(probe.assess(1, captured, changed, trace, [])["unconfirmed_provenance_preserved"])

    def test_mismatch_and_real_components_cannot_be_relabelled_success(self):
        captured = {"billfit_validate_bill": {"status": "mismatch", "checks": [
            {"component": "energy_charge", "reported": 12.34, "calculated": 4.9, "difference": -7.44}]}}
        answer = {"bill_validation_status": "mismatch", "energy_difference": -7.44, "switch_recommended": False, "application_submitted": False}
        checks = probe.assess(2, captured, answer, [{"is_error": False}], [])
        self.assertTrue(checks["mismatch_is_not_success"])
        self.assertTrue(checks["confirmed_components_used"])
        answer.update(bill_validation_status="matched", switch_recommended=True)
        checks = probe.assess(2, captured, answer, [{"is_error": False}], [])
        self.assertFalse(checks["mismatch_is_not_success"])
        self.assertFalse(checks["no_switch_or_application_claim"])
        captured["billfit_validate_bill"]["checks"][0]["reported"] = 98.76
        self.assertFalse(probe.assess(2, captured, answer, [], [])["confirmed_components_used"])

    def test_unknown_billing_is_not_zero_and_bad_counters_are_rejected(self):
        usage = probe.session_usage(SimpleNamespace(session_api_calls=True, session_total_tokens=-1,
            session_cost_status="unknown", session_estimated_cost_usd=0))
        self.assertIsNone(usage["model_api_calls"])
        self.assertIsNone(usage["total_tokens"])
        self.assertIsNone(usage["estimated_cost_usd"])
        self.assertIsNone(usage["billed_cost_usd"])
        usage = probe.session_usage(SimpleNamespace(session_api_calls=2, session_total_tokens=123,
            session_cost_status="included", session_estimated_cost_usd=0, session_cost_source="none"))
        self.assertEqual(usage["model_api_calls"], 2)
        self.assertEqual(usage["estimated_cost_usd"], 0)
        self.assertIsNone(usage["billed_cost_usd"])
