from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from billfit_errors import BillFitError
from billfit_usage import Interval, PACIFIC, load_usage, usage_summary as _usage_summary, split_interval as _split_interval
from billfit_reconciliation import assess_period, compare_component, usage_has_assumptions


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PLUGIN_ROOT / "data"


@lru_cache(maxsize=2)
def _bundled_data_text(filename: str) -> str:
    # Cache immutable text, never a dictionary exposed to callers.
    return (DATA_ROOT / filename).read_text(encoding="utf-8")


def rate_data() -> dict[str, Any]:
    return json.loads(_bundled_data_text("pge_residential_rates_2026-03-01.json"))


def assistance_data() -> dict[str, Any]:
    return json.loads(_bundled_data_text("care_fera_2026-06-01.json"))


def _gate(
    gate_id: str,
    title: str,
    reason: str,
    user_action: str,
    status: str = "waiting_for_user",
) -> dict[str, str]:
    return {
        "id": gate_id,
        "title": title,
        "reason": reason,
        "user_action": user_action,
        "status": status,
    }


HUMAN_GATES: dict[str, dict[str, str]] = {
    "ACCOUNT_LOGIN": _gate(
        "ACCOUNT_LOGIN",
        "Download real usage data",
        "BillFit does not sign in to a utility account or handle credentials.",
        "Sign in to PG&E, choose Usage and rates, View Usage Details, then Green Button Download my data.",
    ),
    "REAL_USAGE_FILE": _gate(
        "REAL_USAGE_FILE",
        "Provide a real usage file",
        "A personalized comparison needs the customer's own interval usage.",
        "Attach or provide the local path to a PG&E Green Button CSV or XML file.",
    ),
    "USAGE_QUALITY_REVIEW": _gate(
        "USAGE_QUALITY_REVIEW",
        "Review usage coverage and input assumptions",
        "Incomplete, coarse or inferred usage cannot establish switching savings.",
        "Confirm source units and durations, resolve gaps, and supply a sufficient usage period.",
    ),
    "BILLING_PERIOD_REVIEW": _gate(
        "BILLING_PERIOD_REVIEW",
        "Confirm the statement period and matching usage",
        "An arithmetic match cannot establish that the usage covers the bill being checked.",
        "Confirm the Pacific start date and exclusive end date from the statement convention; provide complete matching intervals without extra records.",
    ),
    "BASELINE_INFO": _gate(
        "BASELINE_INFO",
        "Confirm baseline territory and service type",
        "E-1 and E-TOU-C use a location- and heating-dependent baseline allowance.",
        "Provide baseline territory P, Q, R, S, T, V, W, X, Y, or Z and choose basic or all-electric service.",
    ),
    "TECHNOLOGY_ELIGIBILITY": _gate(
        "TECHNOLOGY_ELIGIBILITY",
        "Confirm qualifying electric technology",
        "EV2-A and E-ELEC are not available to every residential account.",
        "Confirm whether the home has an EV, battery storage, electric water-heating heat pump, or space-conditioning heat pump.",
    ),
    "OFFICIAL_RATE_CONFIRMATION": _gate(
        "OFFICIAL_RATE_CONFIRMATION",
        "Confirm rates before acting",
        "Utility rates and tariff rules can change after BillFit's verified snapshot.",
        "Open the cited PG&E rate page and confirm the effective date before changing plans.",
    ),
    "RATE_PLAN_CHANGE": _gate(
        "RATE_PLAN_CHANGE",
        "Approve and submit a rate-plan change",
        "Changing a utility rate plan is an external account action.",
        "Review the comparison, sign in to PG&E, and personally confirm any plan change.",
    ),
    "ASSISTANCE_APPLICATION": _gate(
        "ASSISTANCE_APPLICATION",
        "Apply for CARE or FERA",
        "BillFit only screens eligibility and does not submit personal or income information.",
        "Review the official requirements and personally complete the PG&E CARE/FERA application.",
    ),
    "INCOME_BOUNDARY_CONFIRMATION": _gate(
        "INCOME_BOUNDARY_CONFIRMATION",
        "Confirm the fractional-income boundary with PG&E",
        "The supplied income falls between the published whole-dollar CARE maximum and FERA minimum; the maintained sources do not establish a rounding rule.",
        "Keep the original income amount and ask PG&E how to apply the published boundary. Do not round it or treat this screening as eligibility approval or denial.",
    ),
    "MEDICAL_CERTIFICATION": _gate(
        "MEDICAL_CERTIFICATION",
        "Obtain Medical Baseline certification",
        "Medical Baseline eligibility must be certified by an eligible medical practitioner.",
        "Complete the customer portion and ask a qualified practitioner to certify the medical need.",
    ),
}


def list_human_gates() -> dict[str, Any]:
    return {
        "status": "ok",
        "policy": "BillFit may analyze user-provided data but never logs in, changes a plan, submits an application, or certifies medical eligibility.",
        "gates": list(HUMAN_GATES.values()),
    }


def _freshness(rate: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    verified = date.fromisoformat(rate["verified_on"])
    today = as_of or date.today()
    age = (today - verified).days
    effective_to = rate.get("effective_to")
    expired = bool(effective_to and today > date.fromisoformat(effective_to))
    not_yet_effective = today < date.fromisoformat(rate["effective_from"])
    return {
        "verified_on": verified.isoformat(),
        "age_days": age,
        "stale": age > 45 or expired or not_yet_effective or age < 0,
        "verification_overdue": age > 45,
        "outside_effective_window": expired or not_yet_effective,
        "rate_changed": None,
        "effective_from": rate["effective_from"],
        "effective_to": effective_to,
    }


def get_supported_scope() -> dict[str, Any]:
    rates = rate_data()
    assist = assistance_data()
    return {
        "status": "ok",
        "mvp_scope": {
            "utility": "PG&E",
            "customer_type": "individually metered residential bundled electric service",
            "supported_plans": list(rates["plans"].keys()),
            "usage_formats": ["PG&E Green Button CSV", "Green Button ESPI XML", "BillFit interval JSON"],
            "assistance_screening": ["CARE", "FERA", "Medical Baseline"],
            "time_zone": "America/Los_Angeles",
        },
        "not_supported": [
            "CCA or Direct Access generation charges",
            "solar, NEM, net export, or battery export",
            "master-metered service",
            "gas rates",
            "EV-B separately metered service",
            "taxes, local surcharges, Climate Credit, or account-specific adjustments",
        ],
        "rate_snapshot": {
            "status": rates["status"],
            "freshness": _freshness(rates),
            "source": rates["source"],
        },
        "assistance_snapshot": {
            "freshness": _freshness(assist),
            "effective_from": assist["effective_from"],
            "effective_to": assist["effective_to"],
            "source": assist["source"],
        },
        "privacy": "Files are read locally. BillFit does not need account credentials, SSN, medical records, or uploaded income documents for screening.",
        "human_gates": [HUMAN_GATES["ACCOUNT_LOGIN"], HUMAN_GATES["REAL_USAGE_FILE"]],
    }


def parse_usage_file(usage_file: str) -> dict[str, Any]:
    intervals, warnings, source = load_usage(usage_file=usage_file)
    summary = _usage_summary(intervals)
    preview_items = intervals[:3] + (intervals[-3:] if len(intervals) > 3 else [])
    preview = [
        {
            "start": item.start.isoformat(),
            "duration_minutes": item.duration_minutes,
            "kwh": round(item.kwh, 6),
        }
        for item in preview_items
    ]
    gates = []
    if summary["negative_interval_count"]:
        warnings.append("Negative usage indicates export or corrections; solar/net export is outside the MVP scope.")
    return {
        "status": "parsed",
        "source": source,
        "summary": summary,
        "warnings": warnings,
        "preview": preview,
        "next_step": "Call billfit_compare_rate_plans with the same usage_file.",
        "human_gates": gates,
    }


def _normalize_plan(plan: str, *, rates: dict | None = None) -> str:
    key = re.sub(r"[^A-Z0-9]", "", str(plan).upper())
    aliases = {
        "E1": "E-1",
        "ETOUC": "E-TOU-C",
        "ETOUD": "E-TOU-D",
        "EV2": "EV2-A",
        "EV2A": "EV2-A",
        "EELEC": "E-ELEC",
    }
    if key not in aliases:
        raise BillFitError("UNSUPPORTED_PLAN", f"Unsupported rate plan: {plan}", {"supported": list((rate_data() if rates is None else rates)["plans"])})
    return aliases[key]


def _normalize_program(program: str | None) -> str:
    if not program:
        return "none"
    key = re.sub(r"[^a-z]", "", str(program).lower())
    aliases = {"none": "none", "standard": "none", "care": "care", "fera": "fera"}
    if key not in aliases:
        raise BillFitError("UNSUPPORTED_ASSISTANCE_PROGRAM", "assistance_program must be none, CARE, or FERA.")
    return aliases[key]


def _season(moment: datetime) -> str:
    return "summer" if 6 <= moment.month <= 9 else "winter"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=16)
def _holidays(year: int) -> set[date]:
    fixed = [date(year, 1, 1), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    observed = {_observed(day) for day in fixed}
    return observed | {
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
    }


def _is_holiday(day: date) -> bool:
    return day in (_holidays(day.year - 1) | _holidays(day.year) | _holidays(day.year + 1))


def _rate_period(plan: str, moment: datetime) -> str:
    hour = moment.hour + moment.minute / 60
    if plan == "E-TOU-C":
        return "peak" if 16 <= hour < 21 else "off_peak"
    if plan == "E-TOU-D":
        is_weekday = moment.weekday() < 5 and not _is_holiday(moment.date())
        return "peak" if is_weekday and 17 <= hour < 20 else "off_peak"
    if plan in {"EV2-A", "E-ELEC"}:
        if 16 <= hour < 21:
            return "peak"
        if 15 <= hour < 16 or 21 <= hour < 24:
            return "partial_peak"
        return "off_peak"
    raise BillFitError("PLAN_PERIOD_ERROR", f"No time-of-use period rule exists for {plan}.")


def _coverage_minutes_by_day(intervals: list[Interval]) -> dict[date, float]:
    coverage: dict[date, float] = {}
    for interval in intervals:
        for moment, minutes, _ in _split_interval(interval):
            coverage[moment.date()] = coverage.get(moment.date(), 0.0) + minutes
    return coverage


def _baseline_allowance(intervals: list[Interval], territory: str, service_type: str, *, rates: dict | None = None) -> float:
    rates = rate_data() if rates is None else rates
    territory_key = territory.upper().strip()
    service_key = service_type.lower().replace("-", "_").replace(" ", "_")
    if service_key in {"allelectric", "all_elec"}:
        service_key = "all_electric"
    if service_key in {"basic_electric", "basic_elec"}:
        service_key = "basic"
    try:
        baseline = rates["baseline_daily_kwh"][territory_key][service_key]
    except KeyError as exc:
        raise BillFitError(
            "INVALID_BASELINE_INFO",
            "baseline_territory must be P/Q/R/S/T/V/W/X/Y/Z and service_type must be basic or all_electric.",
        ) from exc
    allowance = 0.0
    for day, minutes in _coverage_minutes_by_day(intervals).items():
        midnight = datetime.combine(day, time.min, PACIFIC)
        next_midnight = datetime.combine(day + timedelta(days=1), time.min, PACIFIC)
        day_minutes = (next_midnight.astimezone(timezone.utc) - midnight.astimezone(timezone.utc)).total_seconds() / 60
        fraction = min(1.0, minutes / day_minutes)
        season = "summer" if 6 <= day.month <= 9 else "winter"
        allowance += baseline[season] * fraction
    return allowance


def _check_plan_eligibility(plan: str, technologies: set[str] | None, *, rates: dict | None = None) -> None:
    details = (rate_data() if rates is None else rates)["plans"][plan]
    eligibility = details["eligibility"]
    if eligibility == "general":
        return
    if technologies is None:
        raise BillFitError("ELIGIBILITY_NEEDS_CONFIRMATION", f"{plan} requires confirmation of a qualifying technology.")
    if eligibility == "electric_vehicle" and "electric_vehicle" not in technologies:
        raise BillFitError("PLAN_INELIGIBLE", f"{plan} requires a qualifying electric vehicle.")
    if eligibility == "qualifying_electric_technology":
        required = set(details["qualifying_technologies"])
        if not required.intersection(technologies):
            raise BillFitError("PLAN_INELIGIBLE", f"{plan} requires an EV, battery storage, or qualifying heat pump.")


def _simulate_plan(
    intervals: list[Interval],
    plan: str,
    assistance_program: str,
    baseline_territory: str | None,
    service_type: str | None,
    technologies: set[str] | None,
    *,
    rates: dict | None = None,
    billing_days: int | None = None,
) -> dict[str, Any]:
    rates = rate_data() if rates is None else rates
    details = rates["plans"][plan]
    _check_plan_eligibility(plan, technologies, rates=rates)
    summary = _usage_summary(intervals)
    if summary["negative_interval_count"]:
        raise BillFitError("UNSUPPORTED_NET_EXPORT", "Negative intervals indicate export; solar/net export is outside the MVP scope.")

    total_kwh = sum(interval.kwh for interval in intervals)
    baseline_kwh: float | None = None
    period_kwh: dict[str, float] = {}
    raw_energy_charge = 0.0
    if details["kind"] == "tiered":
        if not baseline_territory or not service_type:
            raise BillFitError("BASELINE_INFO_REQUIRED", "E-1 requires baseline territory and service type.")
        baseline_kwh = _baseline_allowance(intervals, baseline_territory, service_type, rates=rates)
        tier_1_kwh = min(total_kwh, baseline_kwh)
        tier_2_kwh = max(0.0, total_kwh - tier_1_kwh)
        period_kwh = {"tier_1": tier_1_kwh, "tier_2": tier_2_kwh}
        raw_energy_charge = tier_1_kwh * details["tier_1"] + tier_2_kwh * details["tier_2"]
    else:
        for interval in intervals:
            for moment, _, kwh in _split_interval(interval):
                season = _season(moment)
                period = _rate_period(plan, moment)
                key = f"{season}_{period}"
                period_kwh[key] = period_kwh.get(key, 0.0) + kwh
                raw_energy_charge += kwh * details[season][period]
        if details["kind"] == "tou_baseline_credit":
            if not baseline_territory or not service_type:
                raise BillFitError("BASELINE_INFO_REQUIRED", "E-TOU-C requires baseline territory and service type.")
            baseline_kwh = _baseline_allowance(intervals, baseline_territory, service_type, rates=rates)
            raw_energy_charge -= min(total_kwh, baseline_kwh) * details["baseline_credit"]

    discount_rate = rates["assistance_volumetric_discount"][assistance_program]
    assistance_discount = max(0.0, raw_energy_charge * discount_rate)
    energy_after_discount = raw_energy_charge - assistance_discount
    bsc = rates["base_services_charge_per_day"]["standard" if assistance_program == "none" else assistance_program]
    billed_days = summary["billing_days"] if billing_days is None else billing_days
    base_services_charge = bsc * billed_days
    total = energy_after_discount + base_services_charge
    annualized = total / billed_days * 365.2425
    return {
        "status": "calculated",
        "plan": plan,
        "plan_name": details["name"],
        "usage_kwh": round(total_kwh, 6),
        "billing_days": billed_days,
        "baseline_kwh": round(baseline_kwh, 6) if baseline_kwh is not None else None,
        "usage_by_period_kwh": {key: round(value, 6) for key, value in sorted(period_kwh.items())},
        "raw_energy_charge": round(raw_energy_charge, 2),
        "assistance_program": assistance_program.upper() if assistance_program != "none" else "NONE",
        "assistance_discount": round(assistance_discount, 2),
        "energy_charge_after_discount": round(energy_after_discount, 2),
        "base_services_charge": round(base_services_charge, 2),
        "estimated_comparable_total": round(total, 2),
        "annualized_comparable_total": round(annualized, 2),
    }


def _usage_needs_review(summary: dict[str, Any], warnings: list[str]) -> bool:
    return summary["quality"] != "good" or summary["gap_minutes"] > 0 or usage_has_assumptions(warnings)


def compare_rate_plans(
    usage_file: str | None = None,
    intervals: list[dict[str, Any]] | None = None,
    current_plan: str | None = None,
    candidate_plans: list[str] | None = None,
    baseline_territory: str | None = None,
    service_type: str | None = None,
    assistance_program: str | None = None,
    qualifying_technologies: list[str] | None = None,
    solar_or_net_export: bool = False,
    cca_or_direct_access: bool = False,
) -> dict[str, Any]:
    return _compare_rate_snapshot(
        rate_data(), usage_file=usage_file, intervals=intervals, current_plan=current_plan,
        candidate_plans=candidate_plans, baseline_territory=baseline_territory, service_type=service_type,
        assistance_program=assistance_program, qualifying_technologies=qualifying_technologies,
        solar_or_net_export=solar_or_net_export, cca_or_direct_access=cca_or_direct_access,
    )


def _compare_rate_snapshot(
    rates: dict[str, Any],
    *,
    usage_file: str | None = None,
    intervals: list[dict[str, Any]] | None = None,
    current_plan: str | None = None,
    candidate_plans: list[str] | None = None,
    baseline_territory: str | None = None,
    service_type: str | None = None,
    assistance_program: str | None = None,
    qualifying_technologies: list[str] | None = None,
    solar_or_net_export: bool = False,
    cca_or_direct_access: bool = False,
) -> dict[str, Any]:
    """Internal review entry; snapshots are never selected by MCP/CLI arguments."""
    rates = deepcopy(rates)
    if solar_or_net_export:
        raise BillFitError("UNSUPPORTED_SCOPE", "Solar, NEM, and net export are outside the BillFit MVP scope.")
    if cca_or_direct_access:
        raise BillFitError("UNSUPPORTED_SCOPE", "CCA and Direct Access generation charges are outside the BillFit MVP scope.")
    parsed, warnings, source = load_usage(usage_file=usage_file, intervals=intervals)
    summary = _usage_summary(parsed)
    if summary["quality"] == "limited":
        warnings.append("Less than seven days of near-complete data can produce an unstable annualized comparison.")
    program = _normalize_program(assistance_program)
    techs = None if qualifying_technologies is None else {
        re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in qualifying_technologies
    }
    plans = [_normalize_plan(plan, rates=rates) for plan in candidate_plans] if candidate_plans else list(rates["plans"])
    if current_plan:
        normalized_current = _normalize_plan(current_plan, rates=rates)
        if normalized_current not in plans:
            plans.insert(0, normalized_current)
    else:
        normalized_current = None
    plans = list(dict.fromkeys(plans))

    results: list[dict[str, Any]] = []
    gates_by_id: dict[str, dict[str, str]] = {}
    for plan in plans:
        try:
            result = _simulate_plan(
                parsed,
                plan,
                program,
                baseline_territory,
                service_type,
                techs,
                rates=rates,
            )
        except BillFitError as exc:
            status = "ineligible" if exc.code == "PLAN_INELIGIBLE" else "needs_human_input"
            result = {"status": status, "plan": plan, "error": exc.as_dict()}
            if exc.code in {"BASELINE_INFO_REQUIRED", "INVALID_BASELINE_INFO"}:
                gates_by_id["BASELINE_INFO"] = HUMAN_GATES["BASELINE_INFO"]
            if exc.code == "ELIGIBILITY_NEEDS_CONFIRMATION":
                gates_by_id["TECHNOLOGY_ELIGIBILITY"] = HUMAN_GATES["TECHNOLOGY_ELIGIBILITY"]
        results.append(result)

    calculated = sorted(
        (item for item in results if item["status"] == "calculated"),
        key=lambda item: item["annualized_comparable_total"],
    )
    current_result = next((item for item in calculated if item["plan"] == normalized_current), None)
    best = calculated[0] if calculated else None
    recommendation: dict[str, Any]
    if not best:
        recommendation = {
            "status": "needs_human_input",
            "message": "No plan could be calculated with the supplied information.",
        }
    elif current_result:
        annual_savings = current_result["annualized_comparable_total"] - best["annualized_comparable_total"]
        savings_percent = annual_savings / current_result["annualized_comparable_total"] if current_result["annualized_comparable_total"] else 0.0
        if best["plan"] != current_result["plan"] and annual_savings >= 75 and savings_percent >= 0.03:
            recommendation = {
                "status": "review_switch",
                "from_plan": current_result["plan"],
                "to_plan": best["plan"],
                "estimated_annual_savings": round(annual_savings, 2),
                "estimated_savings_percent": round(savings_percent * 100, 2),
                "message": "The difference clears BillFit's $75/year and 3% review threshold; verify the tariff and personally approve any change.",
            }
            gates_by_id["OFFICIAL_RATE_CONFIRMATION"] = HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]
            gates_by_id["RATE_PLAN_CHANGE"] = HUMAN_GATES["RATE_PLAN_CHANGE"]
        else:
            recommendation = {
                "status": "stay_or_difference_too_small",
                "current_plan": current_result["plan"],
                "lowest_calculated_plan": best["plan"],
                "estimated_annual_savings": round(max(0.0, annual_savings), 2),
                "estimated_savings_percent": round(max(0.0, savings_percent) * 100, 2),
                "message": "No alternative clears both BillFit review thresholds.",
            }
    else:
        recommendation = {
            "status": "ranked_without_current_plan",
            "lowest_calculated_plan": best["plan"],
            "message": "Provide the current plan to calculate switch savings.",
        }

    usage_uncertain = _usage_needs_review(summary, warnings)
    if best and usage_uncertain:
        recommendation = {
            "status": "withheld_pending_usage_quality",
            "message": "Calculations are illustrative. Confirm units/durations, resolve every detected gap and provide at least 28 days of supported intervals before switching guidance; no annual saving is established.",
            "lowest_calculated_plan": best["plan"],
        }
        gates_by_id["USAGE_QUALITY_REVIEW"] = HUMAN_GATES["USAGE_QUALITY_REVIEW"]
    freshness = _freshness(rates)
    if freshness["stale"]:
        gates_by_id["OFFICIAL_RATE_CONFIRMATION"] = HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]
        warnings.append("The bundled rate snapshot is older than 45 days or outside its effective window.")
        recommendation = {"status": "withheld_pending_rate_verification",
                          "message": "Snapshot verification is stale or outside its effective window; this does not prove rates changed. Confirm official rules before acting."}
    return {
        "status": "compared" if calculated else "needs_human_input",
        "scope": "PG&E bundled, non-solar, individually metered residential electricity",
        "source": source,
        "usage_summary": summary,
        "rate_snapshot": {
            "freshness": freshness,
            "source": rates["source"],
        },
        "results": results,
        "ranking": [item["plan"] for item in calculated],
        "recommendation": recommendation,
        "warnings": warnings + rates["limitations"],
        "human_gates": list(gates_by_id.values()),
    }


def validate_bill(
    usage_file: str | None = None,
    intervals: list[dict[str, Any]] | None = None,
    current_plan: str | None = None,
    reported_energy_charge: float | None = None,
    reported_base_services_charge: float | None = None,
    baseline_territory: str | None = None,
    service_type: str | None = None,
    assistance_program: str | None = None,
    qualifying_technologies: list[str] | None = None,
    billing_period: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not current_plan:
        raise BillFitError("CURRENT_PLAN_REQUIRED", "current_plan is required for bill validation.")
    rates = rate_data()
    parsed, warnings, source = load_usage(usage_file=usage_file, intervals=intervals)
    plan = _normalize_plan(current_plan, rates=rates)
    program = _normalize_program(assistance_program)
    techs = None if qualifying_technologies is None else {
        re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in qualifying_technologies
    }
    period = assess_period(billing_period, parsed, rates)
    simulated = _simulate_plan(parsed, plan, program, baseline_territory, service_type, techs,
                               rates=rates, billing_days=period["calendar_days"])
    simulated["billing_days_basis"] = "usage_span_estimate" if billing_period is None else "declared_pacific_calendar_period"
    checks: list[dict[str, Any]] = []
    for label, reported, calculated in (
        ("energy_charge", reported_energy_charge, simulated["energy_charge_after_discount"]),
        ("base_services_charge", reported_base_services_charge, simulated["base_services_charge"]),
    ):
        if reported is None:
            continue
        checks.append(compare_component(label, reported, calculated))
    passed = bool(checks) and all(check["within_tolerance"] for check in checks)
    freshness = _freshness(rates)
    summary = _usage_summary(parsed)
    reasons = list(period["required_reviews"])
    assumptions = usage_has_assumptions(warnings)
    if assumptions:
        reasons.append("USAGE_ASSUMPTIONS_REQUIRE_REVIEW")
    if freshness["stale"]:
        reasons.append("RATE_VERIFICATION_REQUIRED")
    needs_usage_review = assumptions or any(reason in reasons for reason in (
        "INCOMPLETE_BILLING_PERIOD", "USAGE_OUTSIDE_BILLING_PERIOD")) or (
        billing_period is None and _usage_needs_review(summary, warnings))
    gates = [] if passed and not freshness["stale"] else [HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]]
    if period["status"] != "covered":
        gates.append(HUMAN_GATES["BILLING_PERIOD_REVIEW"])
    if "RATE_PERIOD_NOT_COVERED" in reasons and not any(g["id"] == "OFFICIAL_RATE_CONFIRMATION" for g in gates):
        gates.append(HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"])
    if needs_usage_review:
        gates.append(HUMAN_GATES["USAGE_QUALITY_REVIEW"])
    if not checks:
        status, message = "needs_information", "Provide the bill's energy charge and/or Base Services Charge; do not use the whole amount due."
    elif not passed:
        status, message = "mismatch", "Comparable components differ beyond tolerance. Explain the mismatch and all evidence gaps before acting."
    elif reasons:
        status, message = "needs_review", "Comparable components match arithmetically, but period, usage or rate evidence still needs review. This is not a validated bill."
    else:
        status, message = "validated", "The supplied comparable components reconcile within tolerance for the declared period; excluded bill items and account eligibility are not validated."
    return {
        "status": status,
        "arithmetic_status": "not_checked" if not checks else "matched" if passed else "mismatch",
        "validation_scope": "comparable_components_only",
        "usage_evidence_status": "needs_review" if needs_usage_review or period["status"] != "covered" else "sufficient_for_current_scope",
        "required_reviews": reasons,
        "billing_period": period,
        "comparison_policy": {"currency": "USD", "precision": "decimal cents",
                              "tolerance": "max(2.00, reported * 0.02), compared before display rounding",
                              "pricing_rounding_certified": False},
        "source": source,
        "checks": checks,
        "rate_freshness": freshness,
        "rate_snapshot": {"freshness": freshness, "source": rates["source"]},
        "simulation": simulated,
        "message": message,
        "warnings": warnings + rates["limitations"],
        "human_gates": gates,
    }


def _income_limit(table: dict[str, Any], household_size: int) -> int:
    if household_size <= 0:
        raise BillFitError("INVALID_HOUSEHOLD_SIZE", "household_size must be at least 1.")
    if household_size <= 8:
        return int(table[str(household_size)])
    return int(table["8"] + (household_size - 8) * table["additional_person"])


def _normalize_public_program(program: str, data: dict[str, Any]) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", program.lower()).strip()
    aliases = data["program_aliases"]
    for alias, canonical in aliases.items():
        if cleaned == re.sub(r"[^a-z0-9]+", " ", alias.lower()).strip():
            return canonical
    underscored = cleaned.replace(" ", "_")
    return aliases.get(underscored, underscored)


def screen_assistance(
    household_size: int,
    gross_annual_household_income: float | None = None,
    enrolled_public_programs: list[str] | None = None,
    medical_baseline_need: bool | None = None,
) -> dict[str, Any]:
    return _screen_assistance_snapshot(assistance_data(), household_size,
        gross_annual_household_income, enrolled_public_programs, medical_baseline_need)


def _screen_assistance_snapshot(
    snapshot: dict[str, Any],
    household_size: int,
    gross_annual_household_income: float | None = None,
    enrolled_public_programs: list[str] | None = None,
    medical_baseline_need: bool | None = None,
    *, as_of: date | None = None,
) -> dict[str, Any]:
    """Internal review seam; public tools cannot select unapproved rules or a date."""
    data = deepcopy(snapshot)
    if type(household_size) is not int or household_size < 1:
        raise BillFitError("INVALID_HOUSEHOLD_SIZE", "household_size must be a positive integer.")
    if gross_annual_household_income is not None and (type(gross_annual_household_income) not in (int, float) or not math.isfinite(gross_annual_household_income) or gross_annual_household_income < 0):
        raise BillFitError("INVALID_INCOME", "Income must be a finite nonnegative number.")
    freshness = _freshness(data, as_of)
    if freshness["outside_effective_window"]:
        return {"status": "rules_outside_effective_window", "rules_freshness": freshness,
                "care": {"status": "not_screened"}, "fera": {"status": "not_screened"},
                "human_gates": [HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]], "source": data["source"]}
    size = int(household_size)
    care_limit = _income_limit(data["care_income_upper_limit"], size)
    fera_limit = _income_limit(data["fera_income_upper_limit"], size)
    normalized_programs = {
        _normalize_public_program(program, data) for program in (enrolled_public_programs or [])
    }
    matching_programs = sorted(normalized_programs.intersection(data["care_categorical_programs"]))
    gates: list[dict[str, str]] = []
    if freshness["stale"]:
        gates.append(HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"])

    if matching_programs:
        care = {
            "status": "likely_eligible",
            "basis": "categorical_program",
            "matching_programs": matching_programs,
            "income_upper_limit": care_limit,
        }
        fera = {"status": "not_primary_path", "reason": "CARE categorical eligibility appears stronger."}
        gates.append(HUMAN_GATES["ASSISTANCE_APPLICATION"])
    elif gross_annual_household_income is None:
        care = {"status": "needs_information", "income_upper_limit": care_limit}
        fera = {"status": "needs_information", "income_lower_bound": care_limit + 1, "income_upper_limit": fera_limit}
    else:
        income = float(gross_annual_household_income)
        if income <= care_limit:
            care = {"status": "likely_eligible", "basis": "income", "income_upper_limit": care_limit}
            fera = {"status": "not_primary_path", "reason": "Income is within the CARE screening range."}
            gates.append(HUMAN_GATES["ASSISTANCE_APPLICATION"])
        elif income < care_limit + 1:
            care = {"status": "likely_not_eligible_by_income", "income_upper_limit": care_limit}
            fera = {
                "status": "needs_official_confirmation",
                "reason_code": "FRACTIONAL_INCOME_BOUNDARY",
                "reason": "Income is above the published CARE maximum but below the displayed whole-dollar FERA minimum. Eligibility at this precision is unresolved.",
                "income_lower_bound": care_limit + 1,
                "income_upper_limit": fera_limit,
                "rounding_policy": "unverified",
            }
            gates.append(HUMAN_GATES["INCOME_BOUNDARY_CONFIRMATION"])
        elif income <= fera_limit:
            care = {"status": "likely_not_eligible_by_income", "income_upper_limit": care_limit}
            fera = {
                "status": "likely_eligible",
                "basis": "income",
                "income_lower_bound": care_limit + 1,
                "income_upper_limit": fera_limit,
            }
            gates.append(HUMAN_GATES["ASSISTANCE_APPLICATION"])
        else:
            care = {"status": "likely_not_eligible_by_income", "income_upper_limit": care_limit}
            fera = {"status": "likely_not_eligible_by_income", "income_upper_limit": fera_limit}

    if medical_baseline_need is True:
        medical = {
            "status": "possible_candidate_needs_certification",
            "basis": "user_reported_medical_need",
            "income_test": "not_applicable",
            "source": "https://www.pge.com/en/account/billing-and-assistance/financial-assistance/medical-baseline-program.html",
        }
        gates.append(HUMAN_GATES["MEDICAL_CERTIFICATION"])
    elif medical_baseline_need is False:
        medical = {"status": "not_indicated_by_user", "income_test": "not_applicable"}
    else:
        medical = {
            "status": "not_screened",
            "question": "Does a full-time resident rely on electricity for a qualifying medical condition or home medical device?",
            "income_test": "not_applicable",
        }

    return {
        "status": "screened",
        "rules_freshness": freshness,
        "household_size": size,
        "gross_annual_household_income": gross_annual_household_income,
        "care": care,
        "fera": fera,
        "medical_baseline": medical,
        "rules_effective": {"from": data["effective_from"], "to": data["effective_to"]},
        "source": data["source"],
        "notes": data["notes"],
        "privacy": "Do not provide SSN, medical records, tax returns, pay stubs, or account credentials to BillFit for this screening.",
        "human_gates": list({gate["id"]: gate for gate in gates}.values()),
    }


PUBLIC_FUNCTIONS = {
    "billfit_get_supported_scope": get_supported_scope,
    "billfit_list_human_gates": list_human_gates,
    "billfit_parse_usage_file": parse_usage_file,
    "billfit_compare_rate_plans": compare_rate_plans,
    "billfit_validate_bill": validate_bill,
    "billfit_screen_assistance": screen_assistance,
}
