"""Exact, source-reviewed program names; never infer enrollment from similar text."""
from __future__ import annotations

import re
import unicodedata

from billfit_errors import BillFitError

MAX_PROGRAMS = 32
MAX_PROGRAM_NAME = 160
MAPPING_CHECKED_ON = '2026-11-01'
SOURCES = (
    'https://www.pge.com/en/account/billing-and-assistance/financial-assistance/care-eligibility.html',
    'https://www.cpuc.ca.gov/care/',
)

# These are names for already supported categorical paths, not new income rules.
# PG&E identifies Healthy Families A & B as Medi-Cal for Families. Preserve the
# existing Medicaid/Medi-Cal canonical ID without inventing age or enrollment.
OFFICIAL_NAMES = {
    'EBT/CalFresh/SNAP (Food Stamps)': 'calfresh_snap',
    'Low Income Home Energy Assistance Program (LIHEAP)': 'liheap',
    'Women, Infants, and Children (WIC)': 'wic',
    'Women, Infants, and Children Program (WIC)': 'wic',
    'CalWORKs (TANF)': 'calworks_tanf',
    'Head Start Income Eligible (Tribal Only)': 'head_start_tribal_only',
    'Supplemental Security Income (SSI)': 'supplemental_security_income',
    'Medi-Cal for Families (Healthy Families A & B)': 'medicaid_medi_cal',
    'Healthy Families A & B': 'medicaid_medi_cal',
    'Medicaid/Medi-Cal (under age 65)': 'medicaid_medi_cal',
    'Medicaid/Medi-Cal (age 65 and over)': 'medicaid_medi_cal',
    'National School Lunch Program (NSLP) - Free Lunch': 'national_school_lunch_program_free_lunch',
}


def _key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKC', value).casefold()).strip()


def _lookup(data: dict) -> dict[str, str]:
    allowed = set(data['care_categorical_programs'])
    entries = {name: name for name in allowed}
    entries.update(data['program_aliases'])
    entries.update(OFFICIAL_NAMES)
    # A historical or separately reviewed snapshot still owns its allowed paths.
    return {_key(label): canonical for label, canonical in entries.items() if canonical in allowed}


def normalize_public_program(program: str, data: dict) -> str:
    cleaned = _key(program)
    return _lookup(data).get(cleaned, cleaned.replace(' ', '_'))


def review_public_programs(programs: list[str] | None, data: dict) -> dict:
    if programs is None:
        programs = []
    if (not isinstance(programs, list) or len(programs) > MAX_PROGRAMS
            or any(not isinstance(value, str) or not value.strip()
                   or len(value) > MAX_PROGRAM_NAME for value in programs)):
        raise BillFitError('INVALID_PUBLIC_PROGRAMS',
            'enrolled_public_programs must contain at most 32 nonempty program names, each at most 160 characters.')
    lookup = _lookup(data)
    matches, unrecognized = [], []
    for index, value in enumerate(programs):
        canonical = lookup.get(_key(value))
        entry = {'input_index': index, 'input': value}
        if canonical is None:
            unrecognized.append(entry)
        else:
            matches.append({**entry, 'canonical_program': canonical})
    return {
        'status': 'needs_confirmation' if unrecognized else ('recognized' if matches else 'not_provided'),
        'matches': matches,
        'unrecognized': unrecognized,
        'mapping_checked_on': MAPPING_CHECKED_ON,
        'sources': list(SOURCES),
        'scope': 'Name recognition only; user-reported enrollment and remaining utility requirements are not verified.',
        'unrecognized_meaning': 'An unrecognized name is unresolved, not proof of ineligibility. Confirm the specific program and its qualifiers; do not use fuzzy or substring matches.',
    }
