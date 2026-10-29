"""Bounded local usage adapters and canonical elapsed-time interval validation.

No tariff selection, assistance decisions, account actions or model calls live here.
Every adapter produces the same validated, nonoverlapping sequence of UTC instants.
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from billfit_errors import BillFitError

PACIFIC = ZoneInfo('America/Los_Angeles')
MAX_USAGE_FILE_BYTES = 50 * 1024 * 1024
MAX_USAGE_INTERVALS = 200_000
MAX_INTERVAL_MINUTES = 1440
MAX_USAGE_SPAN_MINUTES = 3 * 366 * 1440
MAX_TOTAL_ABSOLUTE_KWH = 1e12
SUPPORTED_EXTENSIONS = {'.csv', '.xml', '.json'}


@dataclass(frozen=True)
class Interval:
    start: datetime
    duration_minutes: float
    kwh: float

    @property
    def end(self) -> datetime:
        try:
            return (self.start.astimezone(timezone.utc) + timedelta(minutes=self.duration_minutes)).astimezone(PACIFIC)
        except (ValueError, OverflowError) as exc:
            raise BillFitError('INVALID_INTERVAL_END', 'The interval end cannot be represented safely in the supported datetime range.') from exc


def _number(value: Any, code: str = 'INVALID_USAGE_VALUE') -> float:
    if isinstance(value, bool):
        raise BillFitError(code, 'Boolean values are not numeric usage or durations.')
    text = str(value).strip().replace(',', '').replace('$', '')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        number = float(text)
    except (ValueError, TypeError, OverflowError) as exc:
        raise BillFitError(code, 'A supplied usage or duration is not a finite number.') from exc
    if not math.isfinite(number):
        raise BillFitError(code, 'A supplied usage or duration is not a finite number.')
    return number


def _duration(value: Any) -> float:
    minutes = _number(value, 'INVALID_INTERVAL_DURATION')
    if not 1 / 60 <= minutes <= MAX_INTERVAL_MINUTES:
        raise BillFitError('INVALID_INTERVAL_DURATION', 'An explicit interval must be at least one second and at most 1,440 minutes.')
    return minutes


def _timestamp(value: Any, warnings: list[str]) -> datetime:
    if not isinstance(value, str):
        raise BillFitError('INVALID_TIMESTAMP', 'An interval timestamp must be text.')
    text = value.strip()
    text = text[:-1] + '+00:00' if text.endswith('Z') else text
    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ('%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p', '%m/%d/%y %H:%M',
                    '%m/%d/%y %I:%M %p', '%Y-%m-%d %H:%M', '%Y-%m-%d %I:%M %p'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        raise BillFitError('INVALID_TIMESTAMP', 'Cannot parse the supplied interval timestamp.')
    if parsed.tzinfo is None:
        # Round-trip both folds; normal times resolve to one instant, a fall
        # overlap resolves to two, and a spring gap resolves to none.
        candidates = {}
        for fold in (0, 1):
            candidate = parsed.replace(tzinfo=PACIFIC, fold=fold)
            instant = candidate.astimezone(timezone.utc)
            if instant.astimezone(PACIFIC).replace(tzinfo=None) == parsed:
                candidates[instant] = candidate
        if not candidates:
            raise BillFitError('NONEXISTENT_LOCAL_TIME', 'This local clock time does not exist; supply a valid timestamp with UTC offset.')
        if len(candidates) != 1:
            raise BillFitError('AMBIGUOUS_LOCAL_TIME', 'This repeated local clock time needs an explicit UTC offset; no fold is guessed.')
        parsed = next(iter(candidates.values()))
        warning = 'Timestamps had no UTC offset; BillFit assumed America/Los_Angeles for unambiguous local times.'
        if warning not in warnings:
            warnings.append(warning)
    try:
        return parsed.astimezone(PACIFIC)
    except (ValueError, OverflowError) as exc:
        raise BillFitError('INVALID_TIMESTAMP', 'The timestamp cannot be represented in the local timezone.') from exc


def _finalize(intervals: list[Interval], warnings: list[str]) -> list[Interval]:
    if len(intervals) > MAX_USAGE_INTERVALS:
        raise BillFitError('TOO_MANY_INTERVALS', 'At most 200,000 intervals are supported in one input.')
    ordered = sorted(intervals, key=lambda value: value.start.astimezone(timezone.utc))
    known = [value.duration_minutes for value in ordered if value.duration_minutes > 0]
    instants = sorted({value.start.astimezone(timezone.utc) for value in ordered})
    diffs = [(right - left).total_seconds() / 60 for left, right in zip(instants, instants[1:])]
    fallback = statistics.median(known or [value for value in diffs if 0 < value <= 180] or [15.0])
    inferred = sum(value.duration_minutes == 0 for value in ordered)
    if inferred:
        warnings.append(f'INFERRED_INTERVAL_DURATION: {inferred} missing durations use {fallback:g} minutes; confirm against the source before advice.')
    unique = {}
    removed = 0
    for value in ordered:
        canonical = Interval(value.start, _duration(value.duration_minutes or fallback), _number(value.kwh))
        key = (canonical.start.astimezone(timezone.utc), canonical.duration_minutes)
        if key in unique:
            if unique[key].kwh != canonical.kwh:
                raise BillFitError('CONFLICTING_DUPLICATE_INTERVAL', 'The same interval has conflicting usage; resolve the source records before calculating.')
            removed += 1
        else:
            unique[key] = canonical
    result = list(unique.values())
    if any(abs(value.kwh) > MAX_TOTAL_ABSOLUTE_KWH for value in result) or math.fsum(abs(value.kwh) for value in result) > MAX_TOTAL_ABSOLUTE_KWH:
        raise BillFitError('UNSUPPORTED_USAGE_MAGNITUDE', 'The input exceeds the calculator numeric limit of 1 trillion absolute kWh.')
    span = (result[-1].end.astimezone(timezone.utc) - result[0].start.astimezone(timezone.utc)).total_seconds() / 60
    if span > MAX_USAGE_SPAN_MINUTES:
        raise BillFitError('USAGE_RANGE_TOO_LARGE', 'A single comparison supports at most three leap-year lengths of elapsed usage.')
    for left, right in zip(result, result[1:]):
        if right.start.astimezone(timezone.utc) < left.end.astimezone(timezone.utc):
            raise BillFitError('OVERLAPPING_INTERVALS', 'Usage intervals overlap; separate meters or resolve conflicting source intervals before calculating.')
    if removed:
        warnings.append(f'DUPLICATE_INTERVALS_REMOVED: retained one value for {removed} identical repeated records; usage was not added.')
    if any(value.duration_minutes > 60 for value in result):
        warnings.append('COARSE_INTERVAL_ALLOCATION: intervals longer than one hour require uniform-power allocation; switching guidance is withheld.')
    return result


def _header(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', value.casefold().strip())


def _value(row: dict[str, str], *aliases: str) -> str | None:
    for alias in aliases:
        value = row.get(_header(alias))
        if value is not None and value.strip():
            return value.strip()
    return None


def _energy(value: Any, unit: str) -> float:
    normalized = unit.strip().casefold()
    if normalized in {'72', 'wh', 'watt-hour', 'watt-hours'}:
        return _number(value) / 1000
    if normalized in {'kwh', 'kilowatt-hour', 'kilowatt-hours'}:
        return _number(value)
    raise BillFitError('UNSUPPORTED_UOM', 'Only explicit Wh or kWh energy units are supported; power units cannot be treated as energy.')


def _parse_csv(path: Path) -> tuple[list[Interval], list[str]]:
    warnings: list[str] = []
    try:
        rows = list(csv.reader(path.read_text(encoding='utf-8-sig').splitlines()))
    except (UnicodeError, csv.Error) as exc:
        raise BillFitError('INVALID_CSV', 'The usage CSV must be valid UTF-8 CSV.') from exc
    headers = None
    for index, row in enumerate(rows[:50]):
        names = [_header(cell) for cell in row]
        if any(name in {'usage', 'usagekwh', 'value', 'consumption', 'intervalusage'} for name in names) and any(name in {'date', 'timestamp', 'datetime', 'starttime', 'intervalstart', 'start', 'usagedate'} for name in names):
            headers = names
            break
    if headers is None:
        raise BillFitError('CSV_HEADER_NOT_FOUND', 'Could not find usage and timestamp headers in the first 50 CSV rows.')
    nonempty = [name for name in headers if name]
    if len(nonempty) != len(set(nonempty)):
        raise BillFitError('AMBIGUOUS_CSV_HEADER', 'Duplicate normalized CSV headers cannot be resolved safely.')
    intervals = []
    ignored_gas = 0
    for raw in rows[index + 1:]:
        if not any(cell.strip() for cell in raw):
            continue
        row = dict(zip(headers, raw + [''] * max(0, len(headers) - len(raw))))
        unit = _value(row, 'units', 'unit', 'uom')
        if unit and ('therm' in unit.casefold() or unit.casefold() == 'gas'):
            ignored_gas += 1
            continue
        usage = _value(row, 'usage', 'usage kwh', 'consumption', 'value', 'interval usage')
        if usage is None:
            raise BillFitError('MISSING_USAGE_VALUE', 'A nonempty electric CSV record has no usage; it cannot be silently dropped.')
        if unit is None:
            unit = 'kWh'
            note = 'ASSUMED_USAGE_UNIT: CSV has no unit; confirm kWh before switching guidance.'
            if 'usagekwh' not in headers and note not in warnings:
                warnings.append(note)
        kwh = _energy(usage, unit)
        start_text = _value(row, 'timestamp', 'datetime', 'interval start', 'start datetime', 'start')
        date_text = _value(row, 'date', 'usage date', 'interval date')
        start_time = _value(row, 'start time', 'starttime', 'time')
        if not start_text and date_text and start_time:
            start_text = date_text + ' ' + start_time
        elif not start_text and date_text and 't' in date_text.casefold():
            start_text = date_text
        if not start_text:
            raise BillFitError('MISSING_INTERVAL_TIMESTAMP', 'An electric CSV record has usage but no supported timestamp.')
        start = _timestamp(start_text, warnings)
        duration_text = _value(row, 'duration minutes', 'interval minutes')
        seconds_text = _value(row, 'duration seconds', 'interval seconds')
        if _value(row, 'duration') is not None and duration_text is None and seconds_text is None:
            raise BillFitError('AMBIGUOUS_DURATION_UNIT', 'Use an explicit duration minutes or duration seconds column; units are never guessed from magnitude.')
        candidates = []
        if duration_text is not None:
            candidates.append(_duration(duration_text))
        if seconds_text is not None:
            candidates.append(_duration(_number(seconds_text, 'INVALID_INTERVAL_DURATION') / 60))
        end_text = _value(row, 'end timestamp', 'interval end', 'end datetime')
        end_time = _value(row, 'end time', 'endtime')
        if end_text:
            end = _timestamp(end_text, warnings)
            candidates.append(_duration((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 60))
        elif date_text and end_time:
            end = _timestamp(date_text + ' ' + end_time, warnings)
            if end.astimezone(timezone.utc) <= start.astimezone(timezone.utc):
                end = _timestamp((end.replace(tzinfo=None) + timedelta(days=1)).isoformat(), warnings)
            candidates.append(_duration((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 60))
        if candidates and any(abs(value - candidates[0]) > 1e-6 for value in candidates[1:]):
            raise BillFitError('CONFLICTING_INTERVAL_DURATION', 'Explicit durations disagree with each other or with the interval endpoints.')
        intervals.append(Interval(start, candidates[0] if candidates else 0, kwh))
        if len(intervals) > MAX_USAGE_INTERVALS:
            raise BillFitError('TOO_MANY_INTERVALS', 'At most 200,000 intervals are supported in one input.')
    if not intervals:
        raise BillFitError('NO_ELECTRIC_INTERVALS', 'No electric usage intervals were found in the CSV.')
    if ignored_gas:
        warnings.append(f'IGNORED_GAS_ROWS: {ignored_gas} non-electric rows were excluded from the supported electric scope.')
    return _finalize(intervals, warnings), warnings


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit('}', 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    return next((child.text.strip() for child in element.iter() if _local_name(child) == name and child.text and child.text.strip()), None)


def _parse_xml(path: Path) -> tuple[list[Interval], list[str]]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise BillFitError('INVALID_XML', 'The Green Button XML is not well formed.') from exc
    types = [element for element in root.iter() if _local_name(element) == 'ReadingType']
    if len(types) != 1:
        raise BillFitError('AMBIGUOUS_ESPI_READING_TYPE', 'Exactly one supported ReadingType is required; multiple types need an explicit meter-to-unit mapping.')
    if sum(_local_name(element) == 'UsagePoint' for element in root.iter()) > 1:
        raise BillFitError('MULTIPLE_USAGE_POINTS', 'Separate usage points before comparison; BillFit does not combine accounts or meters.')
    unit = _child_text(types[0], 'uom')
    if unit is None:
        raise BillFitError('UNSUPPORTED_UOM', 'ESPI ReadingType must declare a supported energy unit.')
    try:
        multiplier = int(_child_text(types[0], 'powerOfTenMultiplier') or '0')
        if not -12 <= multiplier <= 12:
            raise ValueError('unsupported multiplier')
    except ValueError as exc:
        raise BillFitError('INVALID_ESPI_MULTIPLIER', 'The ESPI power-of-ten multiplier is invalid or outside the supported range.') from exc
    warnings: list[str] = []
    intervals = []
    for reading in root.iter():
        if _local_name(reading) != 'IntervalReading':
            continue
        start, duration, value = (_child_text(reading, name) for name in ('start', 'duration', 'value'))
        if start is None or duration is None or value is None:
            raise BillFitError('MISSING_ESPI_INTERVAL_FIELD', 'Every ESPI interval needs start, duration and value; incomplete records cannot be dropped or filled.')
        try:
            instant = datetime.fromtimestamp(int(start), tz=timezone.utc).astimezone(PACIFIC)
        except (ValueError, OverflowError, OSError) as exc:
            raise BillFitError('INVALID_TIMESTAMP', 'The ESPI timestamp is outside the supported range.') from exc
        minutes = _duration(_number(duration, 'INVALID_INTERVAL_DURATION') / 60)
        kwh = _energy(_number(value) * 10 ** multiplier, unit)
        intervals.append(Interval(instant, minutes, kwh))
        if len(intervals) > MAX_USAGE_INTERVALS:
            raise BillFitError('TOO_MANY_INTERVALS', 'At most 200,000 intervals are supported in one input.')
    if not intervals:
        raise BillFitError('NO_ESPI_INTERVALS', 'No IntervalReading records were found.')
    return _finalize(intervals, warnings), warnings


def _coerce_intervals(raw: Any, warnings: list[str]) -> list[Interval]:
    if not isinstance(raw, list) or not raw:
        raise BillFitError('INTERVALS_REQUIRED', 'Provide a nonempty list of usage intervals.')
    if len(raw) > MAX_USAGE_INTERVALS:
        raise BillFitError('TOO_MANY_INTERVALS', 'At most 200,000 intervals are supported in one input.')
    intervals = []
    for item in raw:
        if not isinstance(item, dict) or 'start' not in item or 'kwh' not in item:
            raise BillFitError('INVALID_INTERVAL', 'Each interval must be an object with start and kwh.')
        duration = _duration(item['duration_minutes']) if 'duration_minutes' in item else 0
        intervals.append(Interval(_timestamp(item['start'], warnings), duration, _number(item['kwh'])))
    return _finalize(intervals, warnings)


def _parse_json(path: Path) -> tuple[list[Interval], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BillFitError('INVALID_JSON', 'The usage JSON is not valid UTF-8 JSON.') from exc
    warnings: list[str] = []
    return _coerce_intervals(payload.get('intervals') if isinstance(payload, dict) else payload, warnings), warnings


def load_usage(usage_file: str | None = None, intervals: list[dict[str, Any]] | None = None) -> tuple[list[Interval], list[str], str]:
    if (usage_file is None) == (intervals is None):
        raise BillFitError('ONE_USAGE_SOURCE_REQUIRED', 'Provide exactly one of usage_file or intervals.')
    if intervals is not None:
        warnings: list[str] = []
        return _coerce_intervals(intervals, warnings), warnings, 'inline_intervals'
    path = Path(str(usage_file)).expanduser().resolve()
    if not path.is_file():
        raise BillFitError('USAGE_FILE_NOT_FOUND', f'Usage file not found: {path}')
    if path.stat().st_size > MAX_USAGE_FILE_BYTES:
        raise BillFitError('USAGE_FILE_TOO_LARGE', 'Usage files larger than 50 MB are not accepted.')
    extension = path.suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise BillFitError('UNSUPPORTED_FILE_TYPE', 'Supported usage files are CSV, XML and JSON.')
    parsed, warnings = {'.csv': _parse_csv, '.xml': _parse_xml, '.json': _parse_json}[extension](path)
    return parsed, warnings, str(path)


def usage_summary(intervals: list[Interval]) -> dict[str, Any]:
    start = min(intervals, key=lambda value: value.start.astimezone(timezone.utc)).start
    end = max((value.end for value in intervals), key=lambda value: value.astimezone(timezone.utc))
    total_minutes = math.fsum(value.duration_minutes for value in intervals)
    span_minutes = (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 60
    completeness = min(1.0, total_minutes / span_minutes)
    days = span_minutes / 1440
    negative = sum(value.kwh < 0 for value in intervals)
    quality = ('unsupported_net_export' if negative else 'good' if days >= 28 and completeness >= .95
               else 'usable_with_caution' if days >= 7 and completeness >= .85 else 'limited')
    return {'interval_count': len(intervals), 'start': start.isoformat(), 'end': end.isoformat(),
            'span_days': round(days, 3), 'billing_days': max(1, round(days)),
            'total_kwh': round(math.fsum(value.kwh for value in intervals), 6),
            'median_interval_minutes': round(statistics.median(value.duration_minutes for value in intervals), 3),
            'max_interval_minutes': max(value.duration_minutes for value in intervals),
            'coverage_ratio': round(completeness, 4), 'elapsed_minutes': round(span_minutes, 6),
            'gap_minutes': round(max(0, span_minutes - total_minutes), 6),
            'negative_interval_count': negative, 'quality': quality}


def split_interval(interval: Interval, step_minutes: float = 15) -> Iterable[tuple[datetime, float, float]]:
    """Conserve energy across actual clock boundaries, assuming uniform power."""
    quantum = _duration(step_minutes) * 60
    cursor = interval.start.astimezone(timezone.utc)
    end = interval.end.astimezone(timezone.utc)
    while cursor < end:
        boundary_seconds = (math.floor(cursor.timestamp() / quantum) + 1) * quantum - cursor.timestamp()
        next_cursor = cursor + timedelta(seconds=min(boundary_seconds, (end - cursor).total_seconds()))
        minutes = (next_cursor - cursor).total_seconds() / 60
        yield cursor.astimezone(PACIFIC), minutes, interval.kwh * minutes / interval.duration_minutes
        cursor = next_cursor
