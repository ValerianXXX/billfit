from __future__ import annotations

import csv
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PLUGIN_ROOT / "data"
PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_USAGE_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".csv", ".xml", ".json"}


class BillFitError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class Interval:
    start: datetime
    duration_minutes: float
    kwh: float

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


@lru_cache(maxsize=1)
def rate_data() -> dict[str, Any]:
    path = DATA_ROOT / "pge_residential_rates_2026-03-01.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def assistance_data() -> dict[str, Any]:
    path = DATA_ROOT / "care_fera_2026-06-01.json"
    return json.loads(path.read_text(encoding="utf-8"))


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


def _freshness(rate: dict[str, Any]) -> dict[str, Any]:
    verified = date.fromisoformat(rate["verified_on"])
    today = date.today()
    age = (today - verified).days
    effective_to = rate.get("effective_to")
    expired = bool(effective_to and today > date.fromisoformat(effective_to))
    return {
        "verified_on": verified.isoformat(),
        "age_days": age,
        "stale": age > 45 or expired,
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
            "effective_from": assist["effective_from"],
            "effective_to": assist["effective_to"],
            "source": assist["source"],
        },
        "privacy": "Files are read locally. BillFit does not need account credentials, SSN, medical records, or uploaded income documents for screening.",
        "human_gates": [HUMAN_GATES["ACCOUNT_LOGIN"], HUMAN_GATES["REAL_USAGE_FILE"]],
    }


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().strip())


def _first_value(row: dict[str, str], aliases: Iterable[str]) -> str | None:
    for alias in aliases:
        value = row.get(_normalize_header(alias))
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _parse_number(value: str) -> float:
    text = value.strip().replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except ValueError as exc:
        raise BillFitError("INVALID_USAGE_VALUE", f"Cannot parse usage value: {value!r}") from exc


def _parse_datetime_text(value: str, warnings: list[str]) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        pass
    if parsed is None:
        formats = (
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%y %H:%M",
            "%m/%d/%y %I:%M %p",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %I:%M %p",
        )
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise BillFitError("INVALID_TIMESTAMP", f"Cannot parse interval timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PACIFIC)
        warning = "Timestamps had no UTC offset; BillFit assumed America/Los_Angeles."
        if warning not in warnings:
            warnings.append(warning)
    else:
        parsed = parsed.astimezone(PACIFIC)
    return parsed


def _date_and_time(date_text: str, time_text: str, warnings: list[str]) -> datetime:
    return _parse_datetime_text(f"{date_text.strip()} {time_text.strip()}", warnings)


def _deduplicate(intervals: list[Interval]) -> list[Interval]:
    combined: dict[tuple[datetime, float], float] = {}
    for interval in intervals:
        key = (interval.start, interval.duration_minutes)
        combined[key] = combined.get(key, 0.0) + interval.kwh
    return [
        Interval(start=key[0], duration_minutes=key[1], kwh=value)
        for key, value in sorted(combined.items(), key=lambda item: item[0][0])
    ]


def _infer_durations(intervals: list[Interval]) -> list[Interval]:
    known = [i.duration_minutes for i in intervals if i.duration_minutes > 0]
    diffs = [
        (intervals[index + 1].start - intervals[index].start).total_seconds() / 60
        for index in range(len(intervals) - 1)
        if 0 < (intervals[index + 1].start - intervals[index].start).total_seconds() / 60 <= 180
    ]
    fallback = statistics.median(known or diffs or [15.0])
    return [
        Interval(i.start, i.duration_minutes if i.duration_minutes > 0 else fallback, i.kwh)
        for i in intervals
    ]


def _parse_csv(path: Path) -> tuple[list[Interval], list[str]]:
    warnings: list[str] = []
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(raw.splitlines()))
    header_index: int | None = None
    normalized_header: list[str] = []
    for index, row in enumerate(rows[:50]):
        normalized = [_normalize_header(cell) for cell in row]
        has_usage = any(cell in {"usage", "usagekwh", "value", "consumption"} or "usage" in cell for cell in normalized)
        has_time = any(cell in {"date", "timestamp", "datetime", "starttime", "intervalstart", "start"} for cell in normalized)
        if has_usage and has_time:
            header_index = index
            normalized_header = normalized
            break
    if header_index is None:
        raise BillFitError(
            "CSV_HEADER_NOT_FOUND",
            "Could not find a usage and timestamp header in the first 50 CSV rows.",
            {"supported_example": "DATE,START TIME,END TIME,USAGE,UNITS"},
        )

    intervals: list[Interval] = []
    for raw_row in rows[header_index + 1 :]:
        if not any(str(cell).strip() for cell in raw_row):
            continue
        padded = raw_row + [""] * max(0, len(normalized_header) - len(raw_row))
        row = {normalized_header[i]: padded[i] for i in range(len(normalized_header)) if normalized_header[i]}
        usage_text = _first_value(row, ["usage", "usage kwh", "consumption", "value", "interval usage"])
        if usage_text is None:
            continue
        units = (_first_value(row, ["units", "unit", "uom"]) or "kWh").lower()
        if "therm" in units or "gas" in units:
            continue
        kwh = _parse_number(usage_text)
        if "kwh" not in units and re.search(r"(^|\W)wh($|\W)", units):
            kwh /= 1000.0

        timestamp = _first_value(row, ["timestamp", "datetime", "interval start", "start datetime", "start"])
        date_text = _first_value(row, ["date", "usage date", "interval date"])
        start_time = _first_value(row, ["start time", "starttime", "time"])
        if timestamp:
            start = _parse_datetime_text(timestamp, warnings)
        elif date_text and start_time:
            start = _date_and_time(date_text, start_time, warnings)
        elif date_text and "t" in date_text.lower():
            start = _parse_datetime_text(date_text, warnings)
        else:
            continue

        duration_minutes = 0.0
        duration_text = _first_value(row, ["duration minutes", "duration", "interval minutes"])
        if duration_text:
            duration_value = _parse_number(duration_text)
            duration_minutes = duration_value / 60 if duration_value > 240 else duration_value
        end_text = _first_value(row, ["end timestamp", "interval end", "end datetime"])
        end_time = _first_value(row, ["end time", "endtime"])
        if end_text:
            end = _parse_datetime_text(end_text, warnings)
            duration_minutes = (end - start).total_seconds() / 60
        elif date_text and end_time:
            end = _date_and_time(date_text, end_time, warnings)
            if end <= start:
                end += timedelta(days=1)
            duration_minutes = (end - start).total_seconds() / 60
        intervals.append(Interval(start, duration_minutes, kwh))

    if not intervals:
        raise BillFitError("NO_ELECTRIC_INTERVALS", "No electric usage intervals were found in the CSV file.")
    return _deduplicate(_infer_durations(sorted(intervals, key=lambda item: item.start))), warnings


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, wanted: str) -> str | None:
    for child in element.iter():
        if _local_name(child) == wanted and child.text and child.text.strip():
            return child.text.strip()
    return None


def _parse_xml(path: Path) -> tuple[list[Interval], list[str]]:
    warnings: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise BillFitError("INVALID_XML", "The Green Button XML file is not well formed.") from exc

    multiplier_text = next(
        (element.text.strip() for element in root.iter() if _local_name(element) == "powerOfTenMultiplier" and element.text),
        "0",
    )
    uom = next(
        (element.text.strip() for element in root.iter() if _local_name(element) == "uom" and element.text),
        "72",
    )
    try:
        multiplier = int(multiplier_text)
    except ValueError:
        multiplier = 0

    intervals: list[Interval] = []
    for reading in root.iter():
        if _local_name(reading) != "IntervalReading":
            continue
        start_text = _child_text(reading, "start")
        duration_text = _child_text(reading, "duration")
        value_text = _child_text(reading, "value")
        if not start_text or not value_text:
            continue
        try:
            start = datetime.fromtimestamp(int(start_text), tz=timezone.utc).astimezone(PACIFIC)
            duration_minutes = int(duration_text or "900") / 60
            value = float(value_text) * (10**multiplier)
        except ValueError as exc:
            raise BillFitError("INVALID_ESPI_VALUE", "An ESPI interval contains an invalid number.") from exc
        normalized_uom = uom.strip().lower()
        if normalized_uom in {"72", "wh", "watt-hour", "watt-hours"}:
            value /= 1000.0
        elif normalized_uom not in {"kwh", "kilowatt-hour", "kilowatt-hours"}:
            raise BillFitError("UNSUPPORTED_UOM", f"Unsupported Green Button unit of measure: {uom}")
        intervals.append(Interval(start, duration_minutes, value))
    if not intervals:
        raise BillFitError("NO_ESPI_INTERVALS", "No IntervalReading records were found in the Green Button XML file.")
    return _deduplicate(_infer_durations(sorted(intervals, key=lambda item: item.start))), warnings


def _parse_json(path: Path) -> tuple[list[Interval], list[str]]:
    warnings: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BillFitError("INVALID_JSON", "The usage JSON file is not valid JSON.") from exc
    raw_intervals = payload.get("intervals") if isinstance(payload, dict) else payload
    return _coerce_intervals(raw_intervals, warnings), warnings


def _coerce_intervals(raw_intervals: Any, warnings: list[str] | None = None) -> list[Interval]:
    warnings = warnings if warnings is not None else []
    if not isinstance(raw_intervals, list) or not raw_intervals:
        raise BillFitError("INTERVALS_REQUIRED", "Provide a non-empty list of usage intervals.")
    intervals: list[Interval] = []
    for index, item in enumerate(raw_intervals):
        if not isinstance(item, dict):
            raise BillFitError("INVALID_INTERVAL", f"Interval {index} must be an object.")
        if "start" not in item or "kwh" not in item:
            raise BillFitError("INVALID_INTERVAL", f"Interval {index} needs start and kwh fields.")
        start = _parse_datetime_text(str(item["start"]), warnings)
        try:
            kwh = float(item["kwh"])
            duration = float(item.get("duration_minutes", 0))
        except (TypeError, ValueError) as exc:
            raise BillFitError("INVALID_INTERVAL", f"Interval {index} has a non-numeric kwh or duration.") from exc
        intervals.append(Interval(start, duration, kwh))
    return _deduplicate(_infer_durations(sorted(intervals, key=lambda interval: interval.start)))


def load_usage(
    usage_file: str | None = None,
    intervals: list[dict[str, Any]] | None = None,
) -> tuple[list[Interval], list[str], str]:
    if bool(usage_file) == bool(intervals):
        raise BillFitError("ONE_USAGE_SOURCE_REQUIRED", "Provide exactly one of usage_file or intervals.")
    if intervals:
        warnings: list[str] = []
        parsed = _coerce_intervals(intervals, warnings)
        return parsed, warnings, "inline_intervals"
    path = Path(str(usage_file)).expanduser().resolve()
    if not path.is_file():
        raise BillFitError("USAGE_FILE_NOT_FOUND", f"Usage file not found: {path}")
    if path.stat().st_size > MAX_USAGE_FILE_BYTES:
        raise BillFitError("USAGE_FILE_TOO_LARGE", "Usage files larger than 50 MB are not accepted by the MVP.")
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise BillFitError("UNSUPPORTED_FILE_TYPE", f"Supported usage files are: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    parser = {".csv": _parse_csv, ".xml": _parse_xml, ".json": _parse_json}[extension]
    parsed, warnings = parser(path)
    return parsed, warnings, str(path)


def _usage_summary(intervals: list[Interval]) -> dict[str, Any]:
    starts = [interval.start for interval in intervals]
    end = max(interval.end for interval in intervals)
    total_minutes = sum(max(0.0, interval.duration_minutes) for interval in intervals)
    span_minutes = max(1.0, (end - min(starts)).total_seconds() / 60)
    completeness = min(1.0, total_minutes / span_minutes)
    durations = [interval.duration_minutes for interval in intervals if interval.duration_minutes > 0]
    days = span_minutes / 1440
    negative_count = sum(1 for interval in intervals if interval.kwh < 0)
    if negative_count:
        quality = "unsupported_net_export"
    elif days >= 28 and completeness >= 0.95:
        quality = "good"
    elif days >= 7 and completeness >= 0.85:
        quality = "usable_with_caution"
    else:
        quality = "limited"
    return {
        "interval_count": len(intervals),
        "start": min(starts).isoformat(),
        "end": end.isoformat(),
        "span_days": round(days, 3),
        "billing_days": max(1, round(days)),
        "total_kwh": round(sum(interval.kwh for interval in intervals), 6),
        "median_interval_minutes": round(statistics.median(durations or [15.0]), 3),
        "coverage_ratio": round(completeness, 4),
        "negative_interval_count": negative_count,
        "quality": quality,
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


def _normalize_plan(plan: str) -> str:
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
        raise BillFitError("UNSUPPORTED_PLAN", f"Unsupported rate plan: {plan}", {"supported": list(rate_data()["plans"])})
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


def _split_interval(interval: Interval, step_minutes: float = 15.0) -> Iterable[tuple[datetime, float, float]]:
    remaining = max(0.0, interval.duration_minutes)
    cursor = interval.start
    if remaining == 0:
        return
    while remaining > 1e-9:
        minutes = min(step_minutes, remaining)
        yield cursor, minutes, interval.kwh * (minutes / interval.duration_minutes)
        cursor += timedelta(minutes=minutes)
        remaining -= minutes


def _coverage_minutes_by_day(intervals: list[Interval]) -> dict[date, float]:
    coverage: dict[date, float] = {}
    for interval in intervals:
        for moment, minutes, _ in _split_interval(interval):
            coverage[moment.date()] = coverage.get(moment.date(), 0.0) + minutes
    return coverage


def _baseline_allowance(intervals: list[Interval], territory: str, service_type: str) -> float:
    rates = rate_data()
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
        fraction = min(1.0, minutes / 1440.0)
        season = "summer" if 6 <= day.month <= 9 else "winter"
        allowance += baseline[season] * fraction
    return allowance


def _check_plan_eligibility(plan: str, technologies: set[str] | None) -> None:
    details = rate_data()["plans"][plan]
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
) -> dict[str, Any]:
    rates = rate_data()
    details = rates["plans"][plan]
    _check_plan_eligibility(plan, technologies)
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
        baseline_kwh = _baseline_allowance(intervals, baseline_territory, service_type)
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
            baseline_kwh = _baseline_allowance(intervals, baseline_territory, service_type)
            raw_energy_charge -= min(total_kwh, baseline_kwh) * details["baseline_credit"]

    discount_rate = rates["assistance_volumetric_discount"][assistance_program]
    assistance_discount = max(0.0, raw_energy_charge * discount_rate)
    energy_after_discount = raw_energy_charge - assistance_discount
    bsc = rates["base_services_charge_per_day"]["standard" if assistance_program == "none" else assistance_program]
    base_services_charge = bsc * summary["billing_days"]
    total = energy_after_discount + base_services_charge
    annualized = total / summary["billing_days"] * 365.2425
    return {
        "status": "calculated",
        "plan": plan,
        "plan_name": details["name"],
        "usage_kwh": round(total_kwh, 6),
        "billing_days": summary["billing_days"],
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
    plans = [_normalize_plan(plan) for plan in candidate_plans] if candidate_plans else list(rate_data()["plans"])
    if current_plan:
        normalized_current = _normalize_plan(current_plan)
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

    freshness = _freshness(rate_data())
    if freshness["stale"]:
        gates_by_id["OFFICIAL_RATE_CONFIRMATION"] = HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]
        warnings.append("The bundled rate snapshot is older than 45 days or outside its effective window.")
    return {
        "status": "compared" if calculated else "needs_human_input",
        "scope": "PG&E bundled, non-solar, individually metered residential electricity",
        "source": source,
        "usage_summary": summary,
        "rate_snapshot": {
            "freshness": freshness,
            "source": rate_data()["source"],
        },
        "results": results,
        "ranking": [item["plan"] for item in calculated],
        "recommendation": recommendation,
        "warnings": warnings + rate_data()["limitations"],
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
) -> dict[str, Any]:
    if not current_plan:
        raise BillFitError("CURRENT_PLAN_REQUIRED", "current_plan is required for bill validation.")
    parsed, warnings, source = load_usage(usage_file=usage_file, intervals=intervals)
    plan = _normalize_plan(current_plan)
    program = _normalize_program(assistance_program)
    techs = None if qualifying_technologies is None else {
        re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in qualifying_technologies
    }
    simulated = _simulate_plan(parsed, plan, program, baseline_territory, service_type, techs)
    checks: list[dict[str, Any]] = []
    for label, reported, calculated in (
        ("energy_charge", reported_energy_charge, simulated["energy_charge_after_discount"]),
        ("base_services_charge", reported_base_services_charge, simulated["base_services_charge"]),
    ):
        if reported is None:
            continue
        difference = calculated - float(reported)
        tolerance = max(2.0, abs(float(reported)) * 0.02)
        checks.append(
            {
                "component": label,
                "reported": round(float(reported), 2),
                "calculated": calculated,
                "difference": round(difference, 2),
                "tolerance": round(tolerance, 2),
                "within_tolerance": abs(difference) <= tolerance,
            }
        )
    if not checks:
        return {
            "status": "needs_information",
            "message": "Provide the bill's energy charge and/or Base Services Charge; do not use the whole amount due.",
            "simulation": simulated,
            "human_gates": [],
        }
    passed = all(check["within_tolerance"] for check in checks)
    return {
        "status": "validated" if passed else "mismatch",
        "source": source,
        "checks": checks,
        "simulation": simulated,
        "message": "Comparable components reconcile within tolerance." if passed else "Do not act on the comparison until the mismatch is explained.",
        "warnings": warnings + rate_data()["limitations"],
        "human_gates": [] if passed else [HUMAN_GATES["OFFICIAL_RATE_CONFIRMATION"]],
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
    data = assistance_data()
    size = int(household_size)
    care_limit = _income_limit(data["care_income_upper_limit"], size)
    fera_limit = _income_limit(data["fera_income_upper_limit"], size)
    normalized_programs = {
        _normalize_public_program(program, data) for program in (enrolled_public_programs or [])
    }
    matching_programs = sorted(normalized_programs.intersection(data["care_categorical_programs"]))
    gates: list[dict[str, str]] = []

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
