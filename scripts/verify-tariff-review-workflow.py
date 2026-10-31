"""Exercise actual review CLI with a declared synthetic rate change, no activation."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/billfit/skills/billfit/scripts"
sys.path.insert(0, str(SCRIPTS))
import billfit_core as core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root
    output.mkdir(exist_ok=False)
    data_files = [core.DATA_ROOT / name for name in ("pge_residential_rates_2026-03-01.json", "care_fera_2026-06-01.json")]
    before_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_files}
    original = deepcopy(core.rate_data())
    request = {"intervals": [{"start": "2026-07-06T17:00:00-07:00", "duration_minutes": 60, "kwh": 1}],
               "candidate_plans": ["E-TOU-D"]}
    public_before = core.compare_rate_plans(**request)
    candidate = deepcopy(original)
    candidate["status"] = "SYNTHETIC_COUNTERFACTUAL_NOT_A_TARIFF"
    candidate["plans"]["E-TOU-D"]["summer"]["peak"] = .87708
    candidate_path = output / "synthetic-candidate.json"
    candidate_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8", newline="\n")
    commands = [
        ["prepare", "--candidate", str(candidate_path), "--output-dir", str(output / "review"), "--synthetic"],
        ["verify", str(output / "review")],
    ]
    rows = []
    for arguments in commands:
        started = time.perf_counter()
        completed = subprocess.run([sys.executable, str(SCRIPTS / "tariff_review_bundle.py"), *arguments], capture_output=True, text=True, timeout=20)
        assert completed.returncode == 0, "Synthetic review CLI failed"
        result = json.loads(completed.stdout)
        assert result["status"] == "REVIEW_REQUIRED" and result["approval"] is None and result["automatic_activation"] is False
        rows.append({"operation": arguments[0], "status": "PASS", "milliseconds": round((time.perf_counter()-started)*1000, 3), "result": result})
    comparison = json.loads((output / "review/comparison.json").read_text())
    for scenario in comparison["regression_scenarios"]:
        old = {row["plan"]: row for row in scenario["old"]}
        new = {row["plan"]: row for row in scenario["candidate"]}
        for plan in old:
            if plan == "E-TOU-D" and scenario["season"] == "summer":
                assert round(new[plan]["raw_energy_charge"] - old[plan]["raw_energy_charge"], 2) == 1.20
            else:
                assert old[plan] == new[plan]
    public_after = core.compare_rate_plans(**request)
    assert public_after == public_before
    assert public_after["results"][0]["raw_energy_charge"] == .48
    after_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_files}
    assert before_hashes == after_hashes
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "status": "PASS", "synthetic_only": True,
              "cli_operations": rows, "bundled_data_before": before_hashes, "bundled_data_after": after_hashes,
              "public_calculation_unchanged": True, "public_energy_charge_before_after": [.48, .48],
              "counterfactual_summer_24kwh_energy_delta": 1.20, "unchanged_other_plan_season_rows": 9,
              "paired_assistance_snapshot_preserved": True, "source_verified_on_unchanged": original["verified_on"],
              "production_activation": False, "operational_rollback": False, "approved": False,
              "model_calls": 0, "external_account_actions": 0,
              "limits": ["Counterfactual values are not official tariffs", "Snapshot arithmetic replay does not prove a deployed service rollback",
                         "Complete assistance snapshot is preserved; assistance-rule update workflow is not added", "Independent source mapping and owner publication approval remain required"]}
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key:report[key] for key in ("status", "public_energy_charge_before_after", "production_activation", "operational_rollback")}))


if __name__ == "__main__":
    main()
