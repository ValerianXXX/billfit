"""Read-only source checks and candidate comparisons. Never installs new rates."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import billfit_core as core

SOURCES = {
    "rates_page": "https://www.pge.com/tariffs/en/rate-information/electric-rates.html",
    "rates_workbook": "https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx",
    "assistance": "https://www.cpuc.ca.gov/care/",
    "medical": "https://www.pge.com/en/account/billing-and-assistance/financial-assistance/medical-baseline-program.html",
}


def check_sources() -> dict:
    rows = []
    for name, url in SOURCES.items():
        try:
            with urlopen(Request(url, headers={"User-Agent": "BillFit-source-check/0.2"}), timeout=25) as response:
                final = urlparse(response.url)
                if final.scheme != "https" or final.hostname not in {"www.pge.com", "www.cpuc.ca.gov"}:
                    raise ValueError("Unexpected source redirect")
                body = response.read(10_000_001)
                if len(body) > 10_000_000:
                    raise ValueError("Source exceeds download limit")
                digest = hashlib.sha256(body).hexdigest()
                row = {"source": name, "url": url, "bytes": len(body), "sha256": digest, "status": "RETRIEVED"}
                if name == "rates_workbook":
                    expected = core.rate_data()["source"]["workbook_sha256"]
                    row.update(previous_sha256=expected, content_changed=digest != expected,
                               status="CONTENT_CHANGED_REVIEW_REQUIRED" if digest != expected else "BYTE_IDENTICAL")
                rows.append(row)
        except Exception as exc:
            rows.append({"source": name, "url": url, "status": "CHECK_FAILED", "error_type": type(exc).__name__})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "sources": rows,
            "rate_change_confirmed": None, "automatic_activation": False,
            "next_action": "Review the effective date and tariff rules. A changed hash alone does not prove changed rates. No packaged data or verification date was modified."}


def validate_candidate(candidate: dict, baseline: dict) -> None:
    """Require the complete current supported structure; reject NaN/coercion/missing keys."""
    def walk(new, old, path="root"):
        if isinstance(old, dict):
            if not isinstance(new, dict) or set(new) != set(old):
                raise ValueError(f"Unsupported schema at {path}")
            for key in old:
                walk(new[key], old[key], path + "." + key)
        elif isinstance(old, bool):
            if type(new) is not bool or new != old:
                raise ValueError(f"Unsupported rule change at {path}")
        elif isinstance(old, (int, float)):
            if type(new) not in (int, float) or not math.isfinite(new) or not 0 <= new <= 1_000_000:
                raise ValueError(f"Invalid numeric value at {path}")
        elif old is None:
            if new is not None:
                date.fromisoformat(new)
        elif isinstance(old, list):
            if not isinstance(new, list) or any(not isinstance(x, str) for x in new):
                raise ValueError(f"Invalid list at {path}")
        elif not isinstance(new, str):
            raise ValueError(f"Invalid text at {path}")
    walk(candidate, baseline)
    start = date.fromisoformat(candidate["effective_from"])
    date.fromisoformat(candidate["verified_on"])
    if candidate["effective_to"] and date.fromisoformat(candidate["effective_to"]) < start:
        raise ValueError("Invalid effective window")
    if candidate["source"]["workbook_url"] != SOURCES["rates_workbook"]:
        raise ValueError("Unsupported rate source")
    for name in baseline["plans"]:
        for key in ("kind", "eligibility", "requires_baseline"):
            if candidate["plans"][name][key] != baseline["plans"][name][key]:
                raise ValueError("Rule changes require an explicit engine review")


def compare_candidate(candidate: dict) -> dict:
    baseline = core.rate_data()
    validate_candidate(candidate, baseline)
    diffs = []
    def compare(a, b, path=""):
        if isinstance(a, dict):
            for key in a:
                compare(a[key], b[key], f"{path}.{key}".lstrip("."))
        elif a != b:
            diffs.append({"field": path, "old": a, "new": b})
    compare(baseline, candidate)
    # This offline review process is single-threaded and never changes persisted rates.
    original = core.rate_data
    scenarios = []
    try:
        for season, day in [("winter", "2026-02-02"), ("summer", "2026-07-06")]:
            request = {"intervals": [{"start": f"{day}T{h:02d}:00:00-08:00" if season == "winter" else f"{day}T{h:02d}:00:00-07:00", "kwh": 1, "duration_minutes": 60} for h in range(24)],
                       "baseline_territory": "Z", "service_type": "basic", "qualifying_technologies": ["electric_vehicle"]}
            values = []
            for data in [baseline, candidate]:
                core.rate_data = lambda: data
                values.append(core.compare_rate_plans(**request)["results"])
            scenarios.append({"season": season, "old": values[0], "candidate": values[1]})
    finally:
        core.rate_data = original
    return {"status": "REVIEW_REQUIRED", "automatic_activation": False, "differences": diffs,
            "regression_scenarios": scenarios, "approval": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    result = compare_candidate(json.loads(args.candidate.read_text(encoding="utf-8"))) if args.candidate else check_sources()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
