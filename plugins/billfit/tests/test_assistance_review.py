"""Candidate assistance review must preserve public screening and release gates."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


def candidate_rules():
    value = core.assistance_data()
    for name in ("care_income_upper_limit", "fera_income_upper_limit"):
        for key in value[name]:
            value[name][key] += 100
    return value


class AssistanceReviewTests(unittest.TestCase):
    def test_changed_thresholds_include_both_boundaries_and_large_households(self):
        from assistance_review import compare_assistance_candidate
        current = core.assistance_data()
        proposed = candidate_rules()
        result = compare_assistance_candidate(proposed)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["automatic_activation"])
        self.assertIsNone(result["approval"])
        self.assertEqual(len(result["differences"]), 18)
        for size in (1, 2, 3, 8, 9, 12):
            for table in ("care_income_upper_limit", "fera_income_upper_limit"):
                for snapshot in (current, proposed):
                    limit = core._income_limit(snapshot[table], size)
                    for income in (limit - 1, limit, limit + 1):
                        self.assertTrue(any(row["request"] == {"household_size": size,
                            "gross_annual_household_income": income} and row["as_of"] == current["effective_from"]
                            for row in result["screening_scenarios"]), (size, table, income))
        row = next(row for row in result["screening_scenarios"] if row["request"] == {
            "household_size": 1, "gross_annual_household_income": 43281} and row["as_of"] == current["effective_from"])
        self.assertEqual(row["old"]["care"]["status"], "likely_not_eligible_by_income")
        self.assertEqual(row["candidate"]["care"]["status"], "likely_eligible")
        self.assertEqual(core.assistance_data(), current)

    def test_future_rules_replay_at_explicit_dates_without_becoming_current(self):
        from assistance_review import compare_assistance_candidate
        proposed = candidate_rules()
        proposed.update(effective_from="2027-06-01", effective_to="2028-05-31")
        result = compare_assistance_candidate(proposed)
        rows = [row for row in result["screening_scenarios"] if row["request"] == {
            "household_size": 1, "gross_annual_household_income": 0}]
        by_date = {row["as_of"]: row for row in rows}
        self.assertEqual(by_date["2027-05-31"]["candidate"]["status"], "rules_outside_effective_window")
        self.assertEqual(by_date["2027-06-01"]["candidate"]["status"], "screened")
        self.assertEqual(by_date["2028-05-31"]["candidate"]["status"], "screened")
        self.assertEqual(by_date["2028-06-01"]["candidate"]["status"], "rules_outside_effective_window")
        self.assertFalse(by_date["2026-12-11"]["old"]["rules_freshness"]["verification_overdue"])
        self.assertTrue(by_date["2026-12-12"]["old"]["rules_freshness"]["verification_overdue"])

    def test_rejects_coercion_inconsistent_tables_and_scope_changes(self):
        from assistance_review import compare_assistance_candidate
        changes = [
            ("care_income_upper_limit.1", True), ("care_income_upper_limit.1", 43280.5),
            ("care_income_upper_limit.1", -1), ("care_income_upper_limit.1", 43279),
            ("care_income_upper_limit.3", 1), ("fera_income_upper_limit.3", 54640),
            ("fera_income_upper_limit.additional_person", 1),
            ("effective_from", "2026-6-01"), ("effective_to", "2020-01-01"),
            ("verified_on", "2099-01-01"), ("source.url", "https://example.test/"),
            ("schema_version", "2.0"), ("status", "approved"),
            ("care_categorical_programs", ["invented_program"]),
            ("program_aliases", {"snap": "invented_program"}), ("notes", []),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                proposed = core.assistance_data()
                target = proposed
                keys = field.split(".")
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                with self.assertRaises(ValueError):
                    compare_assistance_candidate(proposed)
        for proposed in ([], {}, {**core.assistance_data(), "extra": True}):
            with self.subTest(schema=type(proposed).__name__), self.assertRaises(ValueError):
                compare_assistance_candidate(proposed)

    def test_every_existing_program_and_alias_retains_application_and_medical_gates(self):
        from assistance_review import compare_assistance_candidate
        result = compare_assistance_candidate(candidate_rules())
        for program in set(core.assistance_data()["care_categorical_programs"]) | set(core.assistance_data()["program_aliases"]):
            rows = [row for row in result["screening_scenarios"] if row["request"].get("enrolled_public_programs") == [program]]
            self.assertTrue(rows, program)
            for row in rows:
                for key in ("old", "candidate"):
                    self.assertEqual(row[key]["care"]["basis"], "categorical_program")
                    self.assertIn("ASSISTANCE_APPLICATION", row[key]["human_gate_ids"])
        medical = [row for row in result["screening_scenarios"] if row["request"].get("medical_baseline_need") is True]
        self.assertTrue(medical)
        for row in medical:
            self.assertEqual(row["candidate"]["medical_baseline"]["status"], "possible_candidate_needs_certification")
            self.assertIn("MEDICAL_CERTIFICATION", row["candidate"]["human_gate_ids"])

    def test_candidate_review_cannot_change_concurrent_public_screening(self):
        from assistance_review import compare_assistance_candidate
        proposed = candidate_rules()
        original = core._screen_assistance_snapshot
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []
        def held(data, *args, **kwargs):
            if data["care_income_upper_limit"]["1"] == 43380 and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test synchronization expired")
            return original(data, *args, **kwargs)
        def review():
            try:
                results.append(compare_assistance_candidate(proposed))
            except BaseException as exc:
                errors.append(exc)
        with patch.object(core, "_screen_assistance_snapshot", side_effect=held):
            worker = threading.Thread(target=review)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                proposed["care_income_upper_limit"]["1"] = 999999
                live = core.screen_assistance(1, 43281)
                self.assertEqual(live["care"]["income_upper_limit"], 43280)
                self.assertEqual(live["care"]["status"], "likely_not_eligible_by_income")
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(next(d["new"] for d in results[0]["differences"] if d["field"] == "care_income_upper_limit.1"), 43380)

    def test_public_entry_point_does_not_accept_candidate_or_date_override(self):
        with self.assertRaises(TypeError):
            core.screen_assistance(1, assistance_snapshot=candidate_rules())
        with self.assertRaises(TypeError):
            core.screen_assistance(1, as_of=date(2027, 6, 1))

    def test_assistance_only_bundle_contains_replay_and_preserves_both_baselines(self):
        from tariff_review_bundle import prepare_bundle, verify_bundle
        rates, assistance = core.rate_data(), core.assistance_data()
        with tempfile.TemporaryDirectory(prefix="billfit-assistance-") as temporary:
            path = Path(temporary) / "review"
            manifest = prepare_bundle(None, path, assistance_candidate=candidate_rules(), synthetic_only=True)
            self.assertEqual(manifest["schema_version"], 2)
            baseline = json.loads((path / "baseline.json").read_text())
            proposed = json.loads((path / "candidate.json").read_text())
            self.assertEqual(baseline, {"rates": rates, "assistance": assistance})
            self.assertEqual(proposed["rates"], rates)
            self.assertEqual(proposed["assistance"], candidate_rules())
            self.assertEqual(set(manifest["files"]), {"baseline.json", "candidate.json", "comparison.json",
                "rollback-comparison.json", "assistance-comparison.json", "rollback-assistance-comparison.json"})
            self.assertEqual(manifest["source_verified_on"]["assistance"], assistance["verified_on"])
            self.assertTrue(verify_bundle(path)["assistance_replay_matches"])
            self.assertFalse(verify_bundle(path)["installed_or_activated"])
        self.assertEqual(core.rate_data(), rates)
        self.assertEqual(core.assistance_data(), assistance)

    def test_rehashed_screening_and_rule_policy_tampering_fail(self):
        from tariff_review_bundle import prepare_bundle, verify_bundle
        with tempfile.TemporaryDirectory(prefix="billfit-assistance-tamper-") as temporary:
            path = Path(temporary) / "review"
            prepare_bundle(None, path, assistance_candidate=candidate_rules(), synthetic_only=True)
            manifest_file = path / "manifest.json"
            manifest = json.loads(manifest_file.read_text())
            for change in ({"assistance_policy": "PRESERVE_CURRENT_RULES_UNCHANGED"}, {"approval": True},
                           {"remaining_gates": []}, {"candidate_source_verified_on": {"rates": "2099-01-01", "assistance": "2099-01-01"}}):
                with self.subTest(change=change):
                    manifest_file.write_text(json.dumps({**manifest, **change}))
                    with self.assertRaises(ValueError):
                        verify_bundle(path)
            manifest_file.write_text(json.dumps(manifest))
            filename = "assistance-comparison.json"
            result = json.loads((path / filename).read_text())
            result["screening_scenarios"][0]["candidate"]["status"] = "approved"
            raw = json.dumps(result).encode()
            (path / filename).write_bytes(raw)
            manifest["files"][filename] = hashlib.sha256(raw).hexdigest()
            manifest_file.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify_bundle(path)

    def test_invalid_candidate_leaves_no_directory_or_packaged_rule_changes(self):
        from tariff_review_bundle import prepare_bundle
        proposed = candidate_rules()
        proposed["care_income_upper_limit"]["1"] = "PRIVATE_INPUT_MARKER"
        files = sorted(core.DATA_ROOT.glob("*.json"))
        before = {p.name: p.read_bytes() for p in files}
        with tempfile.TemporaryDirectory(prefix="billfit-bad-assistance-") as temporary:
            path = Path(temporary) / "review"
            with self.assertRaises(ValueError):
                prepare_bundle(None, path, assistance_candidate=proposed, synthetic_only=True)
            self.assertFalse(path.exists())
        self.assertEqual({p.name: p.read_bytes() for p in files}, before)

    def test_actual_cli_prepares_assistance_only_and_redacts_invalid_input(self):
        with tempfile.TemporaryDirectory(prefix="billfit-assistance-cli-") as temporary:
            root = Path(temporary)
            source = root / "candidate.json"
            source.write_text(json.dumps(candidate_rules()))
            command = [sys.executable, str(SCRIPTS / "tariff_review_bundle.py")]
            prepared = subprocess.run(command + ["prepare", "--assistance-candidate", str(source),
                "--output-dir", str(root / "review"), "--synthetic"], capture_output=True, text=True, timeout=20)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertIsNone(json.loads(prepared.stdout)["approval"])
            verified = subprocess.run(command + ["verify", str(root / "review")], capture_output=True, text=True, timeout=20)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["assistance_replay_matches"])
            source.write_text('{"PRIVATE_INPUT_MARKER":true}')
            invalid = subprocess.run(command + ["prepare", "--assistance-candidate", str(source),
                "--output-dir", str(root / "invalid"), "--synthetic"], capture_output=True, text=True, timeout=20)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)["error"]["code"], "TARIFF_REVIEW_FAILED")
            self.assertNotIn("PRIVATE_INPUT_MARKER", invalid.stdout + invalid.stderr)
            self.assertFalse((root / "invalid").exists())
