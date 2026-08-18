from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from billfit_core import (  # noqa: E402
    BillFitError,
    compare_rate_plans,
    get_supported_scope,
    parse_usage_file,
    screen_assistance,
    validate_bill,
)


def interval(start: str, kwh: float, duration_minutes: float = 60) -> dict[str, object]:
    return {"start": start, "duration_minutes": duration_minutes, "kwh": kwh}


class BillFitCoreTests(unittest.TestCase):
    def test_scope_has_versioned_official_source(self) -> None:
        result = get_supported_scope()
        self.assertEqual(result["rate_snapshot"]["freshness"]["effective_from"], "2026-03-01")
        self.assertIn("EV2-A", result["mvp_scope"]["supported_plans"])
        self.assertEqual(
            result["rate_snapshot"]["source"]["workbook_sha256"],
            "e071be6fd457a92da60637fc529c1e4c7a5620ffd83d3ae221819f7e4866995d",
        )

    def test_demo_csv_parses(self) -> None:
        result = parse_usage_file(str(PLUGIN_ROOT / "examples" / "demo_usage.csv"))
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["summary"]["interval_count"], 24)
        self.assertAlmostEqual(result["summary"]["total_kwh"], 12.87, places=6)

    def test_care_income_screen(self) -> None:
        result = screen_assistance(4, gross_annual_household_income=60000)
        self.assertEqual(result["care"]["status"], "likely_eligible")
        self.assertEqual(result["care"]["income_upper_limit"], 66000)
        self.assertIn("ASSISTANCE_APPLICATION", {gate["id"] for gate in result["human_gates"]})

    def test_fera_income_screen(self) -> None:
        result = screen_assistance(4, gross_annual_household_income=70000)
        self.assertEqual(result["fera"]["status"], "likely_eligible")
        self.assertEqual(result["fera"]["income_upper_limit"], 82500)

    def test_care_categorical_screen(self) -> None:
        result = screen_assistance(3, enrolled_public_programs=["SNAP", "Medi-Cal"])
        self.assertEqual(result["care"]["basis"], "categorical_program")
        self.assertIn("calfresh_snap", result["care"]["matching_programs"])
        self.assertIn("medicaid_medi_cal", result["care"]["matching_programs"])

    def test_green_button_espi_xml_parses_wh(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">
  <entry><content><espi:ReadingType><espi:powerOfTenMultiplier>0</espi:powerOfTenMultiplier><espi:uom>72</espi:uom></espi:ReadingType></content></entry>
  <entry><content><espi:IntervalBlock><espi:IntervalReading><espi:timePeriod><espi:duration>900</espi:duration><espi:start>1783346400</espi:start></espi:timePeriod><espi:value>250</espi:value></espi:IntervalReading></espi:IntervalBlock></content></entry>
</feed>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "usage.xml"
            path.write_text(xml, encoding="utf-8")
            result = parse_usage_file(str(path))
        self.assertEqual(result["summary"]["interval_count"], 1)
        self.assertAlmostEqual(result["summary"]["total_kwh"], 0.25, places=6)

    def test_medical_screen_requires_person(self) -> None:
        result = screen_assistance(2, gross_annual_household_income=100000, medical_baseline_need=True)
        self.assertEqual(result["medical_baseline"]["status"], "possible_candidate_needs_certification")
        self.assertIn("MEDICAL_CERTIFICATION", {gate["id"] for gate in result["human_gates"]})

    def test_additional_household_threshold(self) -> None:
        result = screen_assistance(9, gross_annual_household_income=120000)
        self.assertEqual(result["care"]["income_upper_limit"], 122800)
        self.assertEqual(result["care"]["status"], "likely_eligible")

    def test_etou_d_exact_summer_rates(self) -> None:
        result = compare_rate_plans(
            intervals=[
                interval("2026-07-06T17:00:00-07:00", 1),
                interval("2026-07-06T21:00:00-07:00", 1),
            ],
            current_plan="E-TOU-D",
            candidate_plans=["E-TOU-D"],
        )
        plan = result["results"][0]
        self.assertEqual(plan["status"], "calculated")
        self.assertAlmostEqual(plan["raw_energy_charge"], 0.82, places=2)
        self.assertAlmostEqual(plan["base_services_charge"], 0.79, places=2)

    def test_observed_holiday_is_off_peak_for_etou_d(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-03T18:00:00-07:00", 1)],
            candidate_plans=["E-TOU-D"],
        )
        plan = result["results"][0]
        self.assertAlmostEqual(plan["raw_energy_charge"], 0.34, places=2)
        self.assertIn("summer_off_peak", plan["usage_by_period_kwh"])

    def test_e1_uses_baseline_territory(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-06T00:00:00-07:00", 10, 1440)],
            candidate_plans=["E-1"],
            baseline_territory="Z",
            service_type="basic",
        )
        plan = result["results"][0]
        self.assertAlmostEqual(plan["baseline_kwh"], 5.9, places=4)
        expected = 5.9 * 0.32561 + 4.1 * 0.40702
        self.assertAlmostEqual(plan["raw_energy_charge"], round(expected, 2), places=2)

    def test_etou_c_applies_baseline_credit(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-06T17:00:00-07:00", 10, 1440)],
            candidate_plans=["E-TOU-C"],
            baseline_territory="Z",
            service_type="basic",
        )
        plan = result["results"][0]
        self.assertAlmostEqual(plan["baseline_kwh"], 5.9, places=4)
        self.assertGreater(plan["raw_energy_charge"], 0)

    def test_care_discount_and_base_charge(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-06T17:00:00-07:00", 10, 1440)],
            candidate_plans=["E-TOU-D"],
            assistance_program="CARE",
        )
        plan = result["results"][0]
        self.assertAlmostEqual(plan["assistance_discount"], round(plan["raw_energy_charge"] * 0.35, 2), places=2)
        self.assertAlmostEqual(plan["base_services_charge"], 0.20, places=2)

    def test_missing_baseline_becomes_human_gate(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-06T00:00:00-07:00", 1)],
            candidate_plans=["E-1", "E-TOU-D"],
        )
        self.assertEqual(result["results"][0]["status"], "needs_human_input")
        self.assertEqual(result["results"][1]["status"], "calculated")
        self.assertIn("BASELINE_INFO", {gate["id"] for gate in result["human_gates"]})

    def test_ev_plan_needs_technology_confirmation(self) -> None:
        result = compare_rate_plans(
            intervals=[interval("2026-07-06T00:00:00-07:00", 1)],
            candidate_plans=["EV2-A"],
        )
        self.assertEqual(result["results"][0]["error"]["code"], "ELIGIBILITY_NEEDS_CONFIRMATION")
        self.assertIn("TECHNOLOGY_ELIGIBILITY", {gate["id"] for gate in result["human_gates"]})

    def test_solar_fails_closed(self) -> None:
        with self.assertRaises(BillFitError) as context:
            compare_rate_plans(
                intervals=[interval("2026-07-06T00:00:00-07:00", 1)],
                candidate_plans=["E-TOU-D"],
                solar_or_net_export=True,
            )
        self.assertEqual(context.exception.code, "UNSUPPORTED_SCOPE")

    def test_bill_validation_reconciles_components(self) -> None:
        usage = [interval("2026-07-06T17:00:00-07:00", 1)]
        comparison = compare_rate_plans(intervals=usage, candidate_plans=["E-TOU-D"])
        plan = comparison["results"][0]
        validation = validate_bill(
            intervals=usage,
            current_plan="E-TOU-D",
            reported_energy_charge=plan["energy_charge_after_discount"],
            reported_base_services_charge=plan["base_services_charge"],
        )
        self.assertEqual(validation["status"], "validated")


class McpProtocolTests(unittest.TestCase):
    def test_initialize_list_and_call(self) -> None:
        process = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "mcp_server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(PLUGIN_ROOT),
        )
        assert process.stdin is not None
        assert process.stdout is not None
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "billfit_screen_assistance", "arguments": {"household_size": 4, "gross_annual_household_income": 70000}},
            },
        ]
        responses = []
        try:
            for request in requests:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                responses.append(json.loads(process.stdout.readline()))
        finally:
            process.stdin.close()
            process.wait(timeout=5)
            process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "billfit")
        self.assertGreaterEqual(len(responses[1]["result"]["tools"]), 6)
        self.assertEqual(
            responses[2]["result"]["structuredContent"]["fera"]["status"],
            "likely_eligible",
        )


if __name__ == "__main__":
    unittest.main()
