"""Run the optional real local OCR path on one original synthetic fixture."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/billfit/skills/billfit/scripts"))
from bill_input import extract_bill_fields

EXPECTED = {"current_plan": "E-TOU-D", "reported_energy_charge": "12.34",
            "reported_base_services_charge": "0.79", "baseline_territory": "X", "total_kwh": "25.5"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New result file; never overwritten")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output file")
    command = os.environ.get("BILLFIT_TESSERACT_PATH")
    if not command or not Path(command).is_file():
        parser.error("Configure an existing trusted BILLFIT_TESSERACT_PATH")
    version = subprocess.run([command, "--version"], text=True, capture_output=True, timeout=10, check=True).stdout.splitlines()[0]
    fixture = ROOT / "plugins/billfit/tests/fixtures/synthetic-bill.png"
    start = time.perf_counter()
    result = extract_bill_fields(str(fixture))
    elapsed = round((time.perf_counter() - start) * 1000)
    values = {row["field"]: row["value"] for row in result["candidates"]}
    missing = sorted(set(EXPECTED) - set(values))
    wrong = sorted(key for key, value in EXPECTED.items() if key in values and values[key] != value)
    bbox_valid = all(row["source"]["bbox"] and len(row["source"]["bbox"]) == 4
                     and 0 <= row["source"]["bbox"][0] < row["source"]["bbox"][2] <= 1300
                     and 0 <= row["source"]["bbox"][1] < row["source"]["bbox"][3] <= 620
                     for row in result["candidates"])
    reviewed = all(row["status"] == "NEEDS_USER_CONFIRMATION" for row in result["candidates"])
    passed = (not missing and not wrong and not result["conflicting_fields"] and bbox_valid and reviewed
              and "98.76" not in values.values() and not result["automatic_calculation"])
    receipt = {"status": "PASS" if passed else "FAILED", "mode": "REAL_LOCAL_OCR_SYNTHETIC_INPUT",
               "observedAt": datetime.now(timezone.utc).isoformat(), "engine": version,
               "pythonVersion": sys.version.split()[0], "fixture": fixture.name,
               "expectedFieldCount": 5, "missingFields": missing, "wrongFields": wrong,
               "bboxWithinFixture": bbox_valid, "durationMs": elapsed, "cloudCalls": 0,
               "actualDollarCost": None, "result": result,
               "limitations": ["One clean digitally rendered synthetic image", "No real customer bill or noisy photograph", "No native Windows OCR binary exercised"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps({key:receipt[key] for key in ("status", "engine", "missingFields", "wrongFields", "durationMs")}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
