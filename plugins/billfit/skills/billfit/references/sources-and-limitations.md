# BillFit MVP sources and interpretation

## Supported population

BillFit 0.2 supports individually metered PG&E residential bundled electric customers without solar/NEM/net export or CCA/Direct Access. It models E-1, E-TOU-C, E-TOU-D, EV2-A, and E-ELEC. EV-B, master-metered service, gas, export compensation, taxes, local surcharges, Climate Credits, and account adjustments are excluded.

## Rate source

- PG&E Electric Rates page: https://www.pge.com/tariffs/en/rate-information/electric-rates.html
- Current residential workbook: https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx
- Snapshot label: `Residential Inclu TOU (MAR 1, 2026 - Present)`
- BillFit verification date: 2026-10-27 (official workbook byte-identical to the August 18 source record; no numeric change)
- Packaged workbook SHA-256 record: `e071be6fd457a92da60637fc529c1e4c7a5620ffd83d3ae221819f7e4866995d`

The packaged JSON contains exact values read from the official workbook, not the rounded marketing PDF. The workbook itself says it is for comparison and that current tariffs control. Reconfirm the official page before a user changes plans, especially when the snapshot is more than 45 days old.

The Base Services Charge is modeled per billing day at the workbook's income tiers: CARE, FERA/qualifying affordable housing, or standard. CARE and FERA volumetric discounts are estimates applied to comparable energy charges. Actual exemptions and account-specific line items may differ.

## Usage source

PG&E says residential electric usage can be downloaded in 15-minute intervals through Green Button Download My Data:

https://www.pge.com/en/save-energy-and-money/energy-usage-and-tips/understand-my-usage.html

The user must perform the account login and download. BillFit reads a local CSV/XML/JSON file and returns summaries rather than the full interval series.

The October 29 parser uses UTC instants for ordering, duration, duplicate identity and coverage, then converts to Pacific local time for tariff periods. It rejects ambiguous/nonexistent offset-free timestamps. Equal repeated intervals retain one value and a warning; conflicts or overlaps require a corrected source. XML currently requires one ReadingType and no more than one UsagePoint rather than guessing relationships in a multi-meter feed. CSV units are Wh/kWh; a missing unit is an explicit assumption unless the header itself says kWh. Explicit duration fields must name minutes or seconds.

CSV energy columns may be `usage`, `usage (kWh)`, `kwh`, `value`, `consumption` or `interval usage`, with case/spacing normalized. Supply exactly one intended energy column and at most one `unit`/`units`/`uom` column. A `kwh` or `usage (kWh)` header supplies an explicit unit and cannot conflict with a row-level Wh unit. BillFit asks for a corrected source copy rather than choosing between multiple measurements. Preserve the original export and verify units before changing a label; relabeling Wh as kWh would change the meaning by a factor of 1,000.

Allocation inside an interval assumes uniform power. Intervals longer than one hour, inferred durations/units and less than 28 days of near-complete data cannot establish switching savings. A complete month still does not prove annual seasonality or actual savings. Daily baseline fractions use the actual local calendar-day length across DST. BillFit's billing-day estimate and excluded bill items still require reconciliation with the actual bill; a component match is not complete-account validation.

Resource limits are 50 MB, 200,000 input intervals, one second through 1,440 minutes per explicit interval, at most 1,098 elapsed days, and at most one trillion absolute kWh in a request. These are calculator safeguards, not utility eligibility criteria. No customer account scope was broadened.

## Assistance sources

- CPUC CARE/FERA current income rules: https://www.cpuc.ca.gov/care/
- PG&E Medical Baseline: https://www.pge.com/en/account/billing-and-assistance/financial-assistance/medical-baseline-program.html

CARE/FERA rules packaged in BillFit are effective 2026-06-01 through 2027-05-31. The result is a screen, because address, account-holder, dependency, household-income, documentation, and utility-review requirements remain external.

Medical Baseline is not income-based. A user-reported medical need can only produce a possible-candidate result; an eligible medical practitioner must certify it.

## Human boundary

BillFit intentionally leaves these actions waiting for a person:

- utility account login and Green Button download
- confirmation of baseline territory, service/heating type, or qualifying technology
- checking the current tariff before acting
- approving and submitting a rate-plan change
- CARE/FERA application and any requested proof
- Medical Baseline practitioner certification

Do not bypass these gates with browser automation or inferred personal facts.
