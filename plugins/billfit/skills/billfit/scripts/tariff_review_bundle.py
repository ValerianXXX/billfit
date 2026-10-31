"""Prepare/replay a tariff review package. No installer, active pointer or approval."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat

import billfit_core as core
from source_check import _compare_candidate_snapshots

MAX_BYTES = 1_000_000
FILES = ("baseline.json", "candidate.json", "comparison.json", "rollback-comparison.json")
SCRIPTS = Path(__file__).resolve().parent
GATES = ("Independent source-to-cell and effective-date review", "Review changed calculations and scope",
         "Explicit owner approval of an exact version before publication", "Release/install and operational rollback acceptance")
ROLLBACK_SCOPE = "Complete prior rate/assistance files and arithmetic replay; no running service was switched"
MANIFEST_KEYS = {"schema_version", "status", "approval", "automatic_activation", "synthetic_only", "prepared_at",
                 "files", "runtime_lf_hashes", "assistance_policy", "source_verified_on", "remaining_gates", "rollback_scope"}


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _runtime_hashes():
    paths = [SCRIPTS / name for name in ("billfit_core.py", "billfit_usage.py", "billfit_errors.py", "billfit_reconciliation.py", "source_check.py", "tariff_review_bundle.py")]
    paths += [core.DATA_ROOT / name for name in ("pge_residential_rates_2026-03-01.json", "care_fera_2026-06-01.json")]
    return {path.relative_to(core.PLUGIN_ROOT).as_posix(): _sha(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()) for path in paths}


def _read(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size > MAX_BYTES:
        raise ValueError("Review packages require bounded regular files")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Review file exceeds the size limit")
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate review JSON key")
            value[key] = item
        return value
    return raw, json.loads(raw, object_pairs_hook=object_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite review value")))


def prepare_bundle(candidate: dict, output_dir: Path, *, synthetic_only: bool = False) -> dict:
    if type(synthetic_only) is not bool:
        raise ValueError("synthetic_only must be explicit boolean metadata")
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Choose a fresh review directory; existing evidence is never overwritten")
    runtime = _runtime_hashes()
    baseline = {"rates": deepcopy(core.rate_data()), "assistance": deepcopy(core.assistance_data())}
    proposed = {"rates": deepcopy(candidate), "assistance": deepcopy(baseline["assistance"])}
    comparison = _compare_candidate_snapshots(baseline["rates"], proposed["rates"])
    rollback = _compare_candidate_snapshots(baseline["rates"], baseline["rates"])
    if runtime != _runtime_hashes():
        raise ValueError("Calculator or bundled rules changed during review preparation")
    payloads = dict(zip(FILES, (baseline, proposed, comparison, rollback)))
    encoded = {name: _bytes(value) for name, value in payloads.items()}
    if any(len(raw) > MAX_BYTES for raw in encoded.values()):
        raise ValueError("Review package exceeds the per-file size limit")
    manifest = {
        "schema_version": 1, "status": "REVIEW_REQUIRED", "approval": None, "automatic_activation": False,
        "synthetic_only": synthetic_only, "prepared_at": datetime.now(timezone.utc).isoformat(),
        "files": {name: _sha(raw) for name, raw in encoded.items()}, "runtime_lf_hashes": runtime,
        "assistance_policy": "PRESERVE_CURRENT_RULES_UNCHANGED",
        "source_verified_on": {"rates": baseline["rates"]["verified_on"], "assistance": baseline["assistance"]["verified_on"]},
        "remaining_gates": list(GATES), "rollback_scope": ROLLBACK_SCOPE,
    }
    output_dir.mkdir()
    # A partial directory has no final manifest and cannot pass verification.
    for name, raw in encoded.items():
        with (output_dir / name).open("xb") as handle:
            handle.write(raw)
    with (output_dir / "manifest.json").open("xb") as handle:
        handle.write(_bytes(manifest))
    return manifest


def verify_bundle(directory: Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Review directory must not be a symlink")
    _, manifest = _read(directory / "manifest.json")
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS
            or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("status") != "REVIEW_REQUIRED" or manifest.get("approval") is not None
            or manifest.get("automatic_activation") is not False or type(manifest.get("synthetic_only")) is not bool
            or manifest.get("assistance_policy") != "PRESERVE_CURRENT_RULES_UNCHANGED"
            or not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != set(FILES)
            or manifest.get("remaining_gates") != list(GATES) or manifest.get("rollback_scope") != ROLLBACK_SCOPE
            or manifest.get("runtime_lf_hashes") != _runtime_hashes()):
        raise ValueError("Unsupported, approved, stale or altered review manifest")
    try:
        prepared_at = datetime.fromisoformat(manifest["prepared_at"])
        if prepared_at.utcoffset() is None:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Review preparation time must include a timezone") from None
    payloads = {}
    for name in FILES:
        raw, value = _read(directory / name)
        if _sha(raw) != manifest["files"][name]:
            raise ValueError("Review content hash mismatch")
        payloads[name] = value
    baseline, candidate = payloads["baseline.json"], payloads["candidate.json"]
    if (not isinstance(baseline, dict) or set(baseline) != {"rates", "assistance"}
            or not isinstance(candidate, dict) or set(candidate) != {"rates", "assistance"}
            or baseline != {"rates": core.rate_data(), "assistance": core.assistance_data()}
            or baseline["assistance"] != candidate["assistance"]
            or manifest["source_verified_on"] != {"rates": baseline["rates"]["verified_on"], "assistance": baseline["assistance"]["verified_on"]}):
        raise ValueError("The review base or supported assistance rules changed")
    forward = _compare_candidate_snapshots(baseline["rates"], candidate["rates"])
    rollback = _compare_candidate_snapshots(baseline["rates"], baseline["rates"])
    if forward != payloads["comparison.json"] or rollback != payloads["rollback-comparison.json"]:
        raise ValueError("Review or rollback arithmetic no longer matches")
    if manifest["runtime_lf_hashes"] != _runtime_hashes():
        raise ValueError("Calculator or bundled rules changed during verification")
    return {"status": "REVIEW_REQUIRED", "approval": None, "automatic_activation": False,
            "synthetic_only": manifest["synthetic_only"], "calculation_replay_matches": True,
            "rollback_snapshot_replay_matches": True, "installed_or_activated": False,
            "snapshot_hashes": {name: manifest["files"][name] for name in ("baseline.json", "candidate.json")},
            "remaining_gates": manifest["remaining_gates"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="operation", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--candidate", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--synthetic", action="store_true")
    verify = subcommands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            _, candidate = _read(args.candidate)
            result = prepare_bundle(candidate, args.output_dir, synthetic_only=args.synthetic)
        else:
            result = verify_bundle(args.directory)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"status": "error", "error": {"code": "TARIFF_REVIEW_FAILED",
              "message": "Review inputs, source/runtime identity and destination. Preserve existing evidence and use a fresh review directory."}}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
