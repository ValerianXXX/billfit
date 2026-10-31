"""Replay fixed synthetic requests through old/current CLI; no accounts or models."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path("plugins/billfit/skills/billfit")
BASELINE = "2847b4c8deb40485c5e1400347898567b50c7135"


def rows(start, count, kwh=1):
    first = datetime.fromisoformat(start).astimezone(timezone.utc)
    return [{"start": (first + timedelta(hours=i)).isoformat(), "duration_minutes": 60, "kwh": kwh}
            for i in range(count)]


def cases():
    complete = {"intervals": rows("2026-07-06T00:00:00-07:00", 24), "current_plan": "E-TOU-D",
                "reported_energy_charge": 8.62, "reported_base_services_charge": .79,
                "billing_period": {"start_date": "2026-07-06", "end_date_exclusive": "2026-07-07"}}
    short = {"intervals": rows("2026-07-06T17:00:00-07:00", 1), "current_plan": "E-TOU-D", "reported_energy_charge": .48}
    boundary = {**short, "intervals": rows("2026-07-06T17:00:00-07:00", 1, 9.23), "reported_energy_charge": 2.40}
    missing = deepcopy(complete)
    missing["intervals"].pop(0)
    historical = {**complete, "intervals": rows("2026-02-28T00:00:00-08:00", 24), "reported_energy_charge": 8.37,
                  "billing_period": {"start_date": "2026-02-28", "end_date_exclusive": "2026-03-01"}}
    monthly = {"intervals": rows("2026-07-01T00:00:00-07:00", 31 * 24), "current_plan": "E-TOU-D", "candidate_plans": ["E-TOU-D"]}
    del monthly["intervals"][200]
    return [
        ("exact_two_dollar_boundary", "validate", boundary),
        ("one_hour_match_without_dates", "validate", short),
        ("complete_declared_day", "validate", complete),
        ("missing_first_hour", "validate", missing),
        ("subcent_reported_amount", "validate", {**short, "reported_energy_charge": .485}),
        ("rate_snapshot_before_effective_date", "validate", historical),
        ("near_complete_month_with_one_gap", "compare", monthly),
    ]


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def extract_baseline(destination):
    files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE, "--", str(PREFIX.as_posix())], cwd=ROOT, text=True).splitlines()
    for name in files:
        path = Path(name)
        if not (path.parent == PREFIX / "scripts" and path.suffix == ".py" or
                path.parent == PREFIX / "data" and path.name in ("pge_residential_rates_2026-03-01.json", "care_fera_2026-06-01.json")):
            continue
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "show", BASELINE + ":" + name], cwd=ROOT))


def run_cli(checkout, operation, payload, request_file):
    request_file.write_bytes(encoded(payload))
    started = time.perf_counter()
    result = subprocess.run([sys.executable, str(checkout / PREFIX / "scripts/billfit_cli.py"), operation,
                             "--input-file", str(request_file)], capture_output=True, text=True, timeout=30)
    return {"exit_code": result.returncode, "seconds": round(time.perf_counter() - started, 6),
            "stderr_empty": not result.stderr, "result": json.loads(result.stdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    output = parser.parse_args().output_root
    output.mkdir(parents=True, exist_ok=False)
    data_paths = [ROOT / PREFIX / "data" / name for name in ("pge_residential_rates_2026-03-01.json", "care_fera_2026-06-01.json")]
    data_before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_paths}
    observations = []
    with tempfile.TemporaryDirectory(prefix="billfit-reconciliation-replay-") as temporary:
        work = Path(temporary)
        baseline = work / "baseline"
        extract_baseline(baseline)
        for name, operation, payload in cases():
            observations.append({"case": name, "operation": operation,
                                 "request_sha256": hashlib.sha256(encoded(payload)).hexdigest(),
                                 "before": run_cli(baseline, operation, payload, work / "request.json"),
                                 "after": run_cli(ROOT, operation, payload, work / "request.json")})
    (output / "observations.json").write_bytes(encoded(observations))
    after = {row["case"]: row["after"]["result"] for row in observations}
    checks = {
        "decimal_boundary_match": after["exact_two_dollar_boundary"]["checks"][0]["within_tolerance"] is True,
        "short_match_is_review_only": after["one_hour_match_without_dates"]["status"] == "needs_review",
        "complete_day_arithmetic_match": after["complete_declared_day"]["arithmetic_status"] == "matched",
        "missing_hour_reported": after["missing_first_hour"]["billing_period"]["missing_minutes"] == 60,
        "subcent_rejected": after["subcent_reported_amount"].get("error", {}).get("code") == "INVALID_BILL_AMOUNT",
        "historical_rate_gap_disclosed": "RATE_PERIOD_NOT_COVERED" in after["rate_snapshot_before_effective_date"]["required_reviews"],
        "gap_savings_withheld": "estimated_annual_savings" not in after["near_complete_month_with_one_gap"]["recommendation"],
    }
    data_after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_paths}
    checks["packaged_sources_unchanged"] = data_before == data_after
    runtime = {path.name: hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
               for path in (ROOT / PREFIX / "scripts").glob("*.py")}
    receipt = {"observed_at": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
               "baseline": BASELINE, "current_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "python": platform.python_version(), "platform": platform.system(), "cases": len(observations),
               "actual_cli_invocations": 2 * len(observations), "checks": checks,
               "observations_sha256": hashlib.sha256((output / "observations.json").read_bytes()).hexdigest(),
               "source_files_before": data_before, "source_files_after": data_after,
               "runtime_lf_hashes": runtime, "models_called": 0, "account_actions": 0,
               "bill_accuracy_certified": False,
               "limits": ["Development cases, not independent customer bills", "Pricing engine rounding remains a separate open verification item", "Old CLI does not support billing_period; its errors are retained"]}
    (output / "receipt.json").write_bytes(encoded(receipt))
    print(json.dumps(receipt, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
