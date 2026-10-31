"""Real local CLI/SDK and additional monetary/period boundaries; synthetic only."""
import asyncio
from datetime import date, datetime, timedelta
from decimal import Inexact, Rounded, localcontext
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
from billfit_reconciliation import assess_period, compare_component


def request():
    start = datetime.fromisoformat("2026-07-06T00:00:00-07:00")
    # Independent source arithmetic: 21 * .34212 + 3 * .47708 = 8.61576.
    return {"intervals": [{"start": (start + timedelta(hours=i)).isoformat(), "duration_minutes": 60, "kwh": 1} for i in range(24)],
            "current_plan": "E-TOU-D", "reported_energy_charge": 8.62, "reported_base_services_charge": .79,
            "billing_period": {"start_date": "2026-07-06", "end_date_exclusive": "2026-07-07"}}


class BillReconciliationIntegrationTests(unittest.TestCase):
    def check_real_result(self, result):
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertEqual(result["billing_period"]["missing_minutes"], 0)
        self.assertEqual(result["simulation"]["energy_charge_after_discount"], 8.62)
        self.assertEqual(result["simulation"]["base_services_charge"], .79)
        if result["rate_freshness"]["stale"]:
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["required_reviews"], ["RATE_VERIFICATION_REQUIRED"])
        else:
            self.assertEqual(result["status"], "validated")
            self.assertEqual(result["required_reviews"], [])

    def test_percentage_tolerance_is_not_rounded_before_comparison(self):
        over = compare_component("energy_charge", 123.45, 125.92)
        self.assertEqual(over["tolerance"], 2.47)
        self.assertEqual(over["tolerance_unrounded"], "2.4690")
        self.assertFalse(over["within_tolerance"])
        self.assertTrue(compare_component("energy_charge", 123.45, 125.91)["within_tolerance"])
        for reported, calculated in ((100, 102), (100, 98), (2.4, 4.4), (4.4, 2.4)):
            with self.subTest(reported=reported, calculated=calculated):
                self.assertTrue(compare_component("energy_charge", reported, calculated)["within_tolerance"])

    def test_foreign_decimal_context_does_not_change_reconciliation(self):
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            check = compare_component("energy_charge", "2.4000", "4.4000")
            self.assertTrue(check["within_tolerance"])
            self.assertEqual(context.prec, 2)

    def test_coarse_full_day_remains_review_only(self):
        payload = request()
        payload["intervals"] = [{**payload["intervals"][0], "kwh": 24, "duration_minutes": 1440}]
        result = core.validate_bill(**payload)
        self.assertEqual(result["arithmetic_status"], "matched")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("USAGE_ASSUMPTIONS_REQUIRE_REVIEW", result["required_reviews"])

    def test_snapshot_end_date_is_inclusive_but_bill_end_is_exclusive(self):
        rates = core.rate_data()
        rates["effective_to"] = "2026-07-06"
        payload = request()
        rows, _, _ = core.load_usage(intervals=payload["intervals"])
        self.assertTrue(assess_period(payload["billing_period"], rows, rates)["rate_snapshot_covers_period"])
        period = {**payload["billing_period"], "end_date_exclusive": "2026-07-08"}
        self.assertFalse(assess_period(period, rows, rates)["rate_snapshot_covers_period"])

    def test_actual_cli_period_match_gap_subcent_and_recovery(self):
        with tempfile.TemporaryDirectory(prefix="billfit-reconcile-") as directory:
            path = Path(directory) / "synthetic.json"
            def run(payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run([sys.executable, str(SCRIPTS / "billfit_cli.py"), "validate", "--input-file", str(path)],
                                        capture_output=True, text=True, timeout=15)
                return result.returncode, json.loads(result.stdout), result.stderr
            code, result, stderr = run(request())
            self.assertEqual(code, 0, stderr)
            self.check_real_result(result)
            payload = request()
            payload["intervals"].pop(0)
            code, result, _ = run(payload)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["billing_period"]["missing_minutes"], 60)
            code, result, stderr = run({**request(), "reported_energy_charge": 8.625})
            self.assertEqual(code, 2)
            self.assertEqual(result["error"]["code"], "INVALID_BILL_AMOUNT")
            self.assertNotIn("8.625", json.dumps(result) + stderr)
            code, result, _ = run(request())
            self.assertEqual(code, 0)
            self.check_real_result(result)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK unavailable")
    def test_actual_sdk_both_profiles_discovery_errors_and_same_connection_recovery(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        async def scenario(mode):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py"), "--sdk"])
            async with Client(params, mode=mode) as client:
                listing = await client.list_tools()
                self.assertEqual(len(listing.tools), 7)
                valid = await client.call_tool("billfit_validate_bill", request())
                self.assertFalse(valid.is_error)
                self.check_real_result(valid.structured_content)
                wrong = {**request(), "billing_period": {**request()["billing_period"], "approved": True}}
                bad = await client.call_tool("billfit_validate_bill", wrong)
                self.assertTrue(bad.is_error)
                self.assertEqual(bad.structured_content["error"]["code"], "INVALID_ARGUMENTS")
                subcent = await client.call_tool("billfit_validate_bill", {**request(), "reported_energy_charge": 8.625})
                self.assertTrue(subcent.is_error)
                self.assertEqual(subcent.structured_content["error"]["code"], "INVALID_BILL_AMOUNT")
                payload = request()
                payload.pop("billing_period")
                limited = await client.call_tool("billfit_validate_bill", payload)
                self.assertFalse(limited.is_error)
                self.assertEqual(limited.structured_content["status"], "needs_review")
                self.assertEqual(limited.structured_content["arithmetic_status"], "matched")
                recovered = await client.call_tool("billfit_validate_bill", request())
                self.assertFalse(recovered.is_error)
                self.check_real_result(recovered.structured_content)
        for mode in ("2026-07-28", "legacy"):
            with self.subTest(mode=mode):
                asyncio.run(scenario(mode))


if __name__ == "__main__":
    unittest.main()
