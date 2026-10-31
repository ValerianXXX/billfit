"""Real CLI/MCP/local OCR checks on fixed synthetic images; no model or account."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/billfit/skills/billfit/scripts"
FIXTURES = ROOT / "plugins/billfit/tests/fixtures/bill-input-v2"


def verify_result(result, case):
    assert result["status"] == "REVIEW_REQUIRED"
    assert not result["automatic_calculation"] and not result["automatic_confirmation"]
    assert result["source_sha256"] == case["sha256"]
    assert result["image_preparation"]["source_size"] == case["pixel_size"]
    assert result["ocr_page_segmentation"] == "AUTOMATIC_LAYOUT_WITHOUT_OSD"
    actual = Counter((row["field"], row["value"]) for row in result["candidates"])
    expected = Counter((key, value) for key, values in case["expected"].items() for value in values)
    assert actual == expected
    for row in result["candidates"]:
        source = row["source"]
        assert source["sha256"] == case["sha256"] and source["page"] == 1
        assert source["coordinate_system"] == "ORIGINAL_ENCODED_IMAGE_PIXELS"
        assert source["source_polygons"] and "IMAGE_PREPARATION_REQUIRES_REVIEW" in row["quality_flags"]
        assert row["status"] == "NEEDS_USER_CONFIRMATION"


async def sdk_scenario(mode, cases, directory, options):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    environment = {name: os.environ[name] for name in
                   ("BILLFIT_TESSERACT_PATH", "LD_LIBRARY_PATH", "TESSDATA_PREFIX") if name in os.environ}
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py"), "--sdk"], env=environment)
    rows = []
    async with Client(params, mode=mode) as client:
        bad = directory / "synthetic-unreadable.png"
        bad.write_bytes(b"SYNTHETIC_PRIVATE_HEADER")
        rejected = await asyncio.wait_for(client.call_tool("billfit_extract_bill_fields", {"bill_file": str(bad), "ocr_deskew": True}), 35)
        assert rejected.is_error
        assert rejected.structured_content["error"]["code"] == "IMAGE_PREPARATION_FAILED"
        assert "SYNTHETIC_PRIVATE_HEADER" not in json.dumps(rejected.structured_content)
        scope = await asyncio.wait_for(client.call_tool("billfit_get_supported_scope", {}), 5)
        assert not scope.is_error
        for case in cases:
            started = time.perf_counter()
            result = await asyncio.wait_for(client.call_tool("billfit_extract_bill_fields", options(case)), 35)
            assert not result.is_error
            verify_result(result.structured_content, case)
            rows.append({"case": case["id"], "status": "PASS", "milliseconds": round((time.perf_counter()-started)*1000, 3),
                         "result": result.structured_content})
    return {"mode": mode, "status": "PASS", "malformed_input_redacted": True, "same_connection_recovery": True, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_raw = (FIXTURES / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    profile = json.loads((FIXTURES.parent / "bill-image-preparation-v1.json").read_text())
    assert manifest["synthetic_only"] and profile["synthetic_only"]
    assert hashlib.sha256(manifest_raw).hexdigest() == profile["manifest_sha256"]
    cases = [row for row in manifest["cases"] if row["id"] in {"skew-6-degrees", "rotated-90-degrees"}]
    for case in cases:
        assert hashlib.sha256((FIXTURES / case["file"]).read_bytes()).hexdigest() == case["sha256"]
    def options(case):
        return {"bill_file": str(FIXTURES / case["file"]), **profile["default_options"], **profile["case_options"].get(case["id"], {})}
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
              "python": platform.python_version(), "platform": platform.system(),
              "pillow": version("Pillow"), "mcp": version("mcp"), "model_calls": 0, "cloud_calls": 0,
              "actual_dollar_cost": None, "manifest_sha256": profile["manifest_sha256"],
              "operator_interventions": profile["operator_interventions"], "results": []}
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        with tempfile.TemporaryDirectory(prefix="billfit-image-client-") as temporary:
            directory = Path(temporary)
            request = directory / "request.json"
            request.write_text(json.dumps(options(cases[0])), encoding="utf-8")
            started = time.perf_counter()
            completed = subprocess.run([sys.executable, str(SCRIPTS / "billfit_cli.py"), "extract-bill", "--input-file", str(request)],
                                       capture_output=True, text=True, timeout=35)
            try:
                assert completed.returncode == 0
                result = json.loads(completed.stdout)
                verify_result(result, cases[0])
                report["results"].append({"interface": "CLI", "status": "PASS", "case": cases[0]["id"],
                                          "milliseconds": round((time.perf_counter()-started)*1000, 3), "result": result})
            except Exception as error:
                report["results"].append({"interface": "CLI", "status": "FAILED", "error_type": type(error).__name__})
            for mode in ("2026-07-28", "legacy"):
                try:
                    report["results"].append({"interface": "MCP_SDK", **asyncio.run(sdk_scenario(mode, cases, directory, options))})
                except Exception as error:
                    report["results"].append({"interface": "MCP_SDK", "mode": mode, "status": "FAILED", "error_type": type(error).__name__})
        report["temporary_requests_removed"] = not directory.exists()
        report["source_unchanged"] = all(hashlib.sha256((FIXTURES / case["file"]).read_bytes()).hexdigest() == case["sha256"] for case in cases)
        report["status"] = "PASS" if all(row["status"] == "PASS" for row in report["results"]) and report["source_unchanged"] else "FAILED"
        report["limits"] = ["Fixed development fixtures, not real customer bills or independent human acceptance",
                            "Local Linux parser and actual SDK transports; not native Windows Tesseract or a Hermes model session",
                            "Manual quarter-turn supplied; all extracted fields remain unconfirmed"]
        json.dump(report, output, indent=2); output.write("\n")
    print(json.dumps({"status": report["status"], "interfaces": [{key: row[key] for key in ("interface", "mode", "status") if key in row} for row in report["results"]]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
