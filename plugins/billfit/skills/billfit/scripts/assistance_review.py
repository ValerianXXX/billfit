"""Bounded assistance threshold updates for local review, never activation."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import billfit_core as core
from source_check import _canonical_date

TABLES = ("care_income_upper_limit", "fera_income_upper_limit")
SIZES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
FIXED_FIELDS = ("schema_version", "source", "status", "care_categorical_programs", "program_aliases", "notes")


def validate_assistance_candidate(candidate: dict, baseline: dict) -> None:
    if not isinstance(candidate, dict) or set(candidate) != set(baseline):
        raise ValueError("Unsupported assistance schema")
    if any(candidate[key] != baseline[key] for key in FIXED_FIELDS):
        raise ValueError("Assistance source, scope and program changes require an engine review")
    dates = {key: _canonical_date(candidate[key]) for key in ("effective_from", "effective_to", "verified_on")}
    if (dates["effective_to"] < dates["effective_from"] or dates["verified_on"] > date.today()
            or any(not 1900 <= value.year <= 9998 for value in dates.values())):
        raise ValueError("Unsupported assistance effective or verification date")
    for name in TABLES:
        table = candidate[name]
        if not isinstance(table, dict) or set(table) != set(baseline[name]):
            raise ValueError("Incomplete assistance income table")
        if any(type(value) is not int or not 0 < value <= 1_000_000 for value in table.values()):
            raise ValueError("Income thresholds must be positive bounded whole dollars")
        if table["1"] != table["2"] or any(table[str(n)] > table[str(n + 1)] for n in range(1, 8)):
            raise ValueError("Inconsistent household income progression")
    care, fera = (candidate[name] for name in TABLES)
    if (any(fera[str(n)] <= care[str(n)] for n in range(1, 9))
            or fera["additional_person"] < care["additional_person"]):
        raise ValueError("FERA thresholds must remain above CARE, including additional people")


def compare_assistance_candidate(candidate: dict) -> dict:
    return _compare_assistance_snapshots(core.assistance_data(), candidate)


def _compare_assistance_snapshots(baseline: dict, candidate: dict) -> dict:
    baseline, candidate = deepcopy(baseline), deepcopy(candidate)
    validate_assistance_candidate(candidate, baseline)
    differences = []
    for key in ("effective_from", "effective_to", "verified_on"):
        if baseline[key] != candidate[key]:
            differences.append({"field": key, "old": baseline[key], "new": candidate[key]})
    for name in TABLES:
        for key, old in baseline[name].items():
            if old != candidate[name][key]:
                differences.append({"field": f"{name}.{key}", "old": old, "new": candidate[name][key]})

    rows = []
    def add(as_of: date, request: dict):
        results = {}
        for label, snapshot in (("old", baseline), ("candidate", candidate)):
            result = core._screen_assistance_snapshot(snapshot, as_of=as_of, **request)
            results[label] = {key: result[key] for key in (
                "status", "care", "fera", "medical_baseline", "rules_freshness", "rules_effective", "source") if key in result}
            results[label]["human_gate_ids"] = [gate["id"] for gate in result["human_gates"]]
        rows.append({"as_of": as_of.isoformat(), "request": request, **results})

    # Both date domains are explicit. Disjoint windows remain visibly unscreened;
    # a future rule is never silently relabelled as currently effective.
    for as_of in sorted({date.fromisoformat(data["effective_from"]) for data in (baseline, candidate)}):
        for size in SIZES:
            incomes = {0}
            for data in (baseline, candidate):
                for name in TABLES:
                    limit = core._income_limit(data[name], size)
                    incomes.update((limit - 1, limit, limit + 1))
            for income in [None, *sorted(incomes)]:
                add(as_of, {"household_size": size, "gross_annual_household_income": income})
        for program in sorted(set(baseline["care_categorical_programs"]) | set(baseline["program_aliases"])):
            add(as_of, {"household_size": 1, "gross_annual_household_income": 999999,
                        "enrolled_public_programs": [program]})
        for need in (None, False, True):
            add(as_of, {"household_size": 1, "medical_baseline_need": need})

    boundary_dates = set()
    for data in (baseline, candidate):
        start, end, verified = (date.fromisoformat(data[key]) for key in ("effective_from", "effective_to", "verified_on"))
        boundary_dates.update((start - timedelta(days=1), start, end, end + timedelta(days=1),
                               verified + timedelta(days=45), verified + timedelta(days=46)))
    for as_of in sorted(boundary_dates):
        add(as_of, {"household_size": 1, "gross_annual_household_income": 0})
    return {"status": "REVIEW_REQUIRED", "approval": None, "automatic_activation": False,
            "differences": differences, "screening_scenarios": rows,
            "scope": "Synthetic whole-dollar boundary and existing-path regression, not source authentication, enrollment or current-date activation"}
