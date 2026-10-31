"""Actual local CLI and SDK transport; no model, customer data or enrollment."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


class AssistanceBoundaryIntegrationTests(unittest.TestCase):
    def gap_request(self):
        limit = core._income_limit(core.assistance_data()["care_income_upper_limit"], 1)
        return {"household_size": 1, "gross_annual_household_income": limit + .5}

    def assert_uncertain(self, result):
        self.assertEqual(result["status"], "screened")
        self.assertEqual(result["fera"]["status"], "needs_official_confirmation")
        self.assertEqual(result["fera"]["reason_code"], "FRACTIONAL_INCOME_BOUNDARY")
        self.assertIn("INCOME_BOUNDARY_CONFIRMATION", {g["id"] for g in result["human_gates"]})
        self.assertEqual(result["gross_annual_household_income"], self.gap_request()["gross_annual_household_income"])

    def test_actual_cli_preserves_uncertainty_and_standard_edges(self):
        with tempfile.TemporaryDirectory(prefix="billfit-income-") as raw:
            path = Path(raw) / "request.json"
            def run(payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run([sys.executable, str(SCRIPTS / "billfit_cli.py"),
                    "assistance", "--input-file", str(path)], capture_output=True,
                    text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            request = self.gap_request()
            self.assert_uncertain(run(request))
            self.assertEqual(run({**request, "gross_annual_household_income": request["gross_annual_household_income"] + .5})["fera"]["status"], "likely_eligible")
            self.assertEqual(run({**request, "gross_annual_household_income": request["gross_annual_household_income"] - .5})["care"]["status"], "likely_eligible")

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK unavailable")
    def test_actual_sdk_both_profiles_retain_boundary_gate_and_recover(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        async def scenario(mode):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py"), "--sdk"])
            async with Client(params, mode=mode) as client:
                listing = await client.list_tools()
                self.assertIn("billfit_screen_assistance", {tool.name for tool in listing.tools})
                response = await client.call_tool("billfit_screen_assistance", self.gap_request())
                self.assertFalse(response.is_error)
                self.assert_uncertain(response.structured_content)
                invalid = await client.call_tool("billfit_screen_assistance", {**self.gap_request(), "gross_annual_household_income": True})
                self.assertTrue(invalid.is_error)
                # The existing public schema rejects bool-as-number before the
                # calculator's direct-call INVALID_INCOME validation is reached.
                self.assertEqual(invalid.structured_content["error"]["code"], "INVALID_ARGUMENTS")
                recovered = await client.call_tool("billfit_screen_assistance", self.gap_request())
                self.assertFalse(recovered.is_error)
                self.assert_uncertain(recovered.structured_content)
                categorical = await client.call_tool("billfit_screen_assistance", {**self.gap_request(), "enrolled_public_programs": ["SNAP"]})
                self.assertFalse(categorical.is_error)
                self.assertEqual(categorical.structured_content["care"]["status"], "likely_eligible")
                self.assertEqual(categorical.structured_content["fera"]["status"], "not_primary_path")
        for mode in ("2026-07-28", "legacy"):
            with self.subTest(mode=mode):
                asyncio.run(scenario(mode))


if __name__ == "__main__":
    unittest.main()
