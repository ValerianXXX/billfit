"""Non-activating review package: complete snapshots, replay and tamper checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


class TariffReviewBundleTests(unittest.TestCase):
    def test_package_preserves_both_rule_sets_and_is_never_an_approval(self):
        from tariff_review_bundle import prepare_bundle, verify_bundle
        baseline, assistance = deepcopy(core.rate_data()), deepcopy(core.assistance_data())
        candidate = deepcopy(baseline)
        candidate["plans"]["E-TOU-D"]["summer"]["peak"] = .87708
        with tempfile.TemporaryDirectory(prefix="billfit-tariff-bundle-") as temporary:
            path = Path(temporary) / "review"
            receipt = prepare_bundle(candidate, path, synthetic_only=True)
            self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
            self.assertIsNone(receipt["approval"])
            self.assertFalse(receipt["automatic_activation"])
            self.assertTrue(receipt["synthetic_only"])
            self.assertEqual(json.loads((path / "baseline.json").read_text()), {"rates": baseline, "assistance": assistance})
            self.assertEqual(json.loads((path / "candidate.json").read_text()), {"rates": candidate, "assistance": assistance})
            verification = verify_bundle(path)
            self.assertEqual(verification["status"], "REVIEW_REQUIRED")
            self.assertTrue(verification["calculation_replay_matches"])
            self.assertTrue(verification["rollback_snapshot_replay_matches"])
            self.assertFalse(verification["installed_or_activated"])
        self.assertEqual(core.rate_data(), baseline)
        self.assertEqual(core.assistance_data(), assistance)

    def test_existing_destination_is_not_overwritten(self):
        from tariff_review_bundle import prepare_bundle
        with tempfile.TemporaryDirectory(prefix="billfit-existing-review-") as temporary:
            path = Path(temporary)
            sentinel = path / "existing"; sentinel.write_text("KEEP")
            with self.assertRaises(FileExistsError):
                prepare_bundle(core.rate_data(), path, synthetic_only=True)
            self.assertEqual(sentinel.read_text(), "KEEP")
            self.assertEqual(len(list(path.iterdir())), 1)

    def test_modified_snapshot_and_incomplete_package_are_rejected(self):
        from tariff_review_bundle import prepare_bundle, verify_bundle
        with tempfile.TemporaryDirectory(prefix="billfit-altered-review-") as temporary:
            path = Path(temporary) / "review"
            prepare_bundle(core.rate_data(), path, synthetic_only=True)
            source = path / "candidate.json"
            original = source.read_bytes()
            source.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                verify_bundle(path)
            source.write_bytes(original)
            (path / "manifest.json").unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                verify_bundle(path)

    def test_a_forged_approval_does_not_become_a_publish_permission(self):
        from tariff_review_bundle import prepare_bundle, verify_bundle
        with tempfile.TemporaryDirectory(prefix="billfit-no-approval-") as temporary:
            path = Path(temporary) / "review"
            prepare_bundle(core.rate_data(), path, synthetic_only=True)
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["approval"] = {"approved": True}
            (path / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify_bundle(path)

