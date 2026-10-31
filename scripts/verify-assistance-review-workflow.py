"""Run the maintenance CLI with synthetic rules; preserve receipts, never activate."""
import argparse
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


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root
    output.mkdir(exist_ok=False)
    files = sorted(core.DATA_ROOT.glob("*.json"))
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    rows = []
    ordinary_input = {"household_size": 1, "gross_annual_household_income": 43281}
    request_path = output / "synthetic-screen-request.json"
    write(request_path, ordinary_input)

    def invoke(label, script, arguments, expected=0):
        started = time.perf_counter()
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                                capture_output=True, text=True, timeout=20)
        elapsed = time.perf_counter() - started
        record = {"operation": label, "exit_code": result.returncode, "elapsed_seconds": round(elapsed, 6),
                  "stdout": result.stdout, "stderr": result.stderr}
        write(output / f"{label}.json", record)
        rows.append({key: record[key] for key in ("operation", "exit_code", "elapsed_seconds")})
        if result.returncode != expected:
            raise AssertionError("Unexpected synthetic CLI result; preserved observation remains available")
        return json.loads(result.stdout)

    public_before = invoke("public-before", "billfit_cli.py", ["assistance", "--input-file", request_path])
    proposed = core.assistance_data()
    for table in ("care_income_upper_limit", "fera_income_upper_limit"):
        for key in proposed[table]:
            proposed[table][key] += 100
    candidate_path = output / "SYNTHETIC-NOT-OFFICIAL-assistance.json"
    write(candidate_path, proposed)
    manifest = invoke("prepare", "tariff_review_bundle.py", ["prepare", "--assistance-candidate", candidate_path,
        "--output-dir", output / "review", "--synthetic"])
    verified = invoke("verify", "tariff_review_bundle.py", ["verify", output / "review"])
    public_after = invoke("public-after", "billfit_cli.py", ["assistance", "--input-file", request_path])
    # An existing review remains intact; the rejected retry is an observation,
    # not permission to replace the package or create another active version.
    rejected = invoke("reject-overwrite", "tariff_review_bundle.py", ["prepare", "--assistance-candidate", candidate_path,
        "--output-dir", output / "review", "--synthetic"], expected=2)
    comparison = json.loads((output / "review/assistance-comparison.json").read_text())
    row = next(row for row in comparison["screening_scenarios"] if row["request"] == ordinary_input
               and row["as_of"] == proposed["effective_from"])
    checks = {
        "public_screening_unchanged": public_before == public_after,
        "baseline_screening_still_uses_original_limit": public_after["care"]["income_upper_limit"] == 43280,
        "counterfactual_boundary_change_visible": row["old"]["care"]["status"] == "likely_not_eligible_by_income"
            and row["candidate"]["care"]["status"] == "likely_eligible",
        "assistance_replay_passed": verified["assistance_replay_matches"] is True,
        "no_activation_or_approval": verified["installed_or_activated"] is False and manifest["approval"] is None
            and manifest["automatic_activation"] is False,
        "overwrite_rejected": rejected["error"]["code"] == "TARIFF_REVIEW_FAILED",
        "packaged_files_unchanged": before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    }
    receipt = {"observed_at": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
        "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "cli_operations": rows,
        "screening_scenarios": len(comparison["screening_scenarios"]), "changed_fields": len(comparison["differences"]),
        "bundled_data_sha256": before, "model_calls": 0, "external_account_actions": 0,
        "production_activation": False, "operational_rollback": False, "independent_human_acceptance": False,
        "limits": ["Counterfactual threshold changes are not official rules or eligibility decisions",
            "Inherited snapshot status/source metadata does not authenticate changed values",
            "Whole-dollar boundary matrix does not establish fractional-income rounding policy",
            "Replay checks preserved data; no installed service was switched"]}
    write(output / "receipt.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "checks", "screening_scenarios", "changed_fields")}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
