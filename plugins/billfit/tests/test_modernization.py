from __future__ import annotations
import asyncio
import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core
from bill_input import extract_bill_fields, extract_spans
from source_check import compare_candidate, validate_candidate


class FreshnessTests(unittest.TestCase):
    def test_age_is_not_evidence_of_rate_change(self):
        data = {**core.rate_data(), "verified_on": "2026-08-18"}
        result = core._freshness(data, date(2026, 10, 27))
        self.assertTrue(result["verification_overdue"])
        self.assertFalse(result["outside_effective_window"])
        self.assertIsNone(result["rate_changed"])
        self.assertFalse(core._freshness(data, date(2026, 10, 2))["stale"])
        self.assertTrue(core._freshness(data, date(2026, 10, 3))["stale"])

    def test_stale_snapshot_withholds_switch_recommendation(self):
        data = {**core.rate_data(), "verified_on": "2000-01-01"}
        with patch.object(core, "rate_data", return_value=data):
            result = core.compare_rate_plans(intervals=[{"start": "2026-07-06T17:00:00-07:00", "kwh": 1}], candidate_plans=["E-TOU-D"])
        self.assertEqual(result["recommendation"]["status"], "withheld_pending_rate_verification")
        self.assertIn("OFFICIAL_RATE_CONFIRMATION", {x["id"] for x in result["human_gates"]})

    def test_expired_assistance_and_invalid_income_fail_closed(self):
        data = {**core.assistance_data(), "effective_to": "2000-01-01"}
        with patch.object(core, "assistance_data", return_value=data):
            self.assertEqual(core.screen_assistance(2, 100)["care"]["status"], "not_screened")
        for size, income in [(True, 100), (1.5, 100), (2, -1), (2, float("nan")), (2, float("inf"))]:
            with self.assertRaises(core.BillFitError):
                core.screen_assistance(size, income)

    def test_candidate_review_and_regression_do_not_activate(self):
        old = copy.deepcopy(core.rate_data())
        same = compare_candidate(copy.deepcopy(old))
        self.assertEqual(same["differences"], [])
        for scenario in same["regression_scenarios"]:
            self.assertEqual(scenario["old"], scenario["candidate"])
            self.assertEqual(len(scenario["old"]), 5)
        candidate = copy.deepcopy(old)
        candidate["plans"]["E-1"]["tier_1"] += 0.01
        changed = compare_candidate(candidate)
        self.assertEqual(changed["status"], "REVIEW_REQUIRED")
        self.assertFalse(changed["automatic_activation"])
        self.assertEqual(core.rate_data(), old)
        for value in [-1, float("nan"), "0.5", True]:
            candidate["plans"]["E-1"]["tier_1"] = value
            with self.assertRaises(ValueError):
                validate_candidate(candidate, old)


class InputTests(unittest.TestCase):
    def test_candidate_evidence_conflict_and_no_total_due(self):
        result = extract_spans([{"page": 2, "line": 7, "text": "Energy Charges $12.34; Amount Due $98.76"},
                               {"page": 3, "line": 2, "text": "Energy Charges $56.78"}], "synthetic-sha", "TEST")
        self.assertEqual(result["conflicting_fields"], ["reported_energy_charge"])
        self.assertEqual(result["candidates"][0]["source"]["page"], 2)
        self.assertNotIn("98.76", [x["value"] for x in result["candidates"]])
        self.assertFalse(result["automatic_confirmation"])

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "optional PDF dependencies unavailable")
    def test_real_pdf_fixture_extraction(self):
        # Small valid original synthetic PDF; no customer/account data.
        lines = ["SYNTHETIC BILL", "Rate Schedule: E-TOU-D", "Energy Charges $12.34", "Base Services Charge $0.79", "Usage 25.5 kWh"]
        stream = "BT /F1 12 Tf 50 750 Td " + " 0 -20 Td ".join(f"({line}) Tj" for line in lines) + " ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                   f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode()]
        pdf = b"%PDF-1.4\n"; offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(pdf)); pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref = len(pdf)
        pdf += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(f"{x:010d} 00000 n \n".encode() for x in offsets[1:])
        pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"; path.write_bytes(pdf)
            result = extract_bill_fields(str(path))
        values = {x["field"]: x["value"] for x in result["candidates"]}
        self.assertEqual(values["current_plan"], "E-TOU-D")
        self.assertEqual(values["reported_energy_charge"], "12.34")
        self.assertEqual(values["reported_base_services_charge"], "0.79")
        self.assertEqual(values["total_kwh"], "25.5")
        self.assertTrue(all(x["source"]["page"] == 1 for x in result["candidates"]))

    def test_image_path_requires_local_ocr_without_upload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"BILLFIT_TESSERACT_PATH": ""}):
            path = Path(directory) / "synthetic.png"; path.write_bytes(b"not an actual image")
            with self.assertRaises(core.BillFitError) as error:
                extract_bill_fields(str(path))
            self.assertEqual(error.exception.code, "LOCAL_OCR_REQUIRED")


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK unavailable")
class SdkTests(unittest.TestCase):
    def test_real_stdio_current_and_legacy_business_tools(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        async def scenario(mode):
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py"), "--sdk"])
            async with Client(params, mode=mode) as client:
                self.assertEqual(client.protocol_version, "2026-07-28" if mode != "legacy" else "2025-11-25")
                tools = await client.list_tools()
                self.assertEqual(len(tools.tools), 7)
                result = await client.call_tool("billfit_screen_assistance", {"household_size": 4, "gross_annual_household_income": 70000})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["fera"]["status"], "likely_eligible")
                invalid = await client.call_tool("billfit_screen_assistance", {"household_size": "4"})
                self.assertTrue(invalid.is_error)
                compare = await client.call_tool("billfit_compare_rate_plans", {"intervals": [{"start": "2026-07-06T17:00:00-07:00", "kwh": 1}], "candidate_plans": ["E-TOU-D"]})
                self.assertFalse(compare.is_error)
                self.assertEqual(compare.structured_content["results"][0]["raw_energy_charge"], 0.48)
        for mode in ["2026-07-28", "legacy"]:
            asyncio.run(scenario(mode))
