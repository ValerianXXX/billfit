"""Bill-period evidence and decimal comparison of already priced components.

This does not set tariffs, infer statement dates, impute missing usage, or certify
the utility's line-item rounding. The pricing engine remains separate.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_UP, localcontext
import re

from billfit_errors import BillFitError
from billfit_usage import PACIFIC

CENT = Decimal("0.01")
MAX_BILL_AMOUNT = Decimal("1e15")
PERIOD_KEYS = {"start_date", "end_date_exclusive"}
ASSUMPTION_MARKERS = ("INFERRED_INTERVAL_DURATION", "ASSUMED_USAGE_UNIT", "COARSE_INTERVAL_ALLOCATION")


def usage_has_assumptions(warnings):
    return any(marker in warning for warning in warnings for marker in ASSUMPTION_MARKERS)


def _amount(value):
    try:
        if type(value) not in (int, float, str):
            raise ValueError
        text = str(value)
        if len(text) > 128:
            raise ValueError
        amount = Decimal(text)
        if not amount.is_finite() or not 0 <= amount <= MAX_BILL_AMOUNT:
            raise ValueError
        cents = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        if amount != cents:
            raise ValueError
        return cents
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise BillFitError("INVALID_BILL_AMOUNT", "Comparable bill amounts must be nonnegative finite USD cents, at most 1e15; do not round an ambiguous field silently.") from exc


def compare_component(label, reported, calculated):
    # Fix the context so another library's Decimal settings cannot change a check.
    with localcontext(Context(prec=40, rounding=ROUND_HALF_UP, traps=[InvalidOperation, DivisionByZero, Overflow])):
        amount, expected = _amount(reported), _amount(calculated)
        difference = expected - amount
        tolerance = max(Decimal("2.00"), amount * Decimal("0.02"))
        return {
            "component": label, "reported": float(amount), "calculated": float(expected),
            "difference": float(difference),
            "tolerance": float(tolerance.quantize(CENT, rounding=ROUND_HALF_UP)),
            "tolerance_unrounded": format(tolerance, "f"),
            "within_tolerance": abs(difference) <= tolerance,
        }


def _microseconds(delta):
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def assess_period(period, intervals, rates):
    if period is None:
        return {"status": "needs_confirmation", "calendar_days": None,
                "required_reviews": ["BILLING_PERIOD_REQUIRED"]}
    try:
        if type(period) is not dict or set(period) != PERIOD_KEYS:
            raise ValueError
        if any(type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, flags=re.ASCII)
               for value in period.values()):
            raise ValueError
        start_date, end_date = (date.fromisoformat(period[key]) for key in ("start_date", "end_date_exclusive"))
        days = (end_date - start_date).days
        if not 1 <= days <= 1098:
            raise ValueError
        start = datetime.combine(start_date, time.min, PACIFIC).astimezone(timezone.utc)
        end = datetime.combine(end_date, time.min, PACIFIC).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise BillFitError("INVALID_BILLING_PERIOD", "Provide only start_date and end_date_exclusive as YYYY-MM-DD Pacific calendar dates, with a positive span of at most 1,098 days. Confirm the source convention; no inclusive end is guessed.") from exc

    expected = _microseconds(end - start)
    covered = 0
    outside = 0
    # The usage adapter already rejects overlaps. Do not alter any source record.
    for item in intervals:
        left, right = item.start.astimezone(timezone.utc), item.end.astimezone(timezone.utc)
        outside += int(left < start or right > end)
        covered += max(0, _microseconds(min(right, end) - max(left, start)))
    missing = max(0, expected - covered)
    reasons = []
    if missing:
        reasons.append("INCOMPLETE_BILLING_PERIOD")
    if outside:
        reasons.append("USAGE_OUTSIDE_BILLING_PERIOD")
    last_date = end_date - timedelta(days=1)
    rate_covers = start_date >= date.fromisoformat(rates["effective_from"]) and (
        not rates.get("effective_to") or last_date <= date.fromisoformat(rates["effective_to"]))
    if not rate_covers:
        reasons.append("RATE_PERIOD_NOT_COVERED")
    return {
        "status": "covered" if not reasons else "needs_review",
        **period, "time_zone": "America/Los_Angeles", "end_convention": "exclusive",
        "calendar_days": days, "expected_minutes": expected / 60_000_000,
        "covered_minutes": covered / 60_000_000, "missing_minutes": missing / 60_000_000,
        "coverage_ratio": round(covered / expected, 6), "outside_interval_count": outside,
        "rate_snapshot_covers_period": rate_covers, "required_reviews": reasons,
        "source": "caller_supplied_dates_not_independently_verified",
    }
