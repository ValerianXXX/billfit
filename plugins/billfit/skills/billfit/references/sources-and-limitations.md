# BillFit MVP sources and interpretation

## Supported population

BillFit 0.2 supports individually metered PG&E residential bundled electric customers without solar/NEM/net export or CCA/Direct Access. It models E-1, E-TOU-C, E-TOU-D, EV2-A, and E-ELEC. EV-B, master-metered service, gas, export compensation, taxes, local surcharges, Climate Credits, and account adjustments are excluded.

## Rate source

- PG&E Electric Rates page: https://www.pge.com/tariffs/en/rate-information/electric-rates.html
- Current residential workbook: https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx
- Snapshot label: `Residential Inclu TOU (MAR 1, 2026 - Present)`
- BillFit verification date: 2026-08-18
- Packaged workbook SHA-256 record: `e071be6fd457a92da60637fc529c1e4c7a5620ffd83d3ae221819f7e4866995d`

The packaged JSON contains exact values read from the official workbook, not the rounded marketing PDF. The workbook itself says it is for comparison and that current tariffs control. Reconfirm the official page before a user changes plans, especially when the snapshot is more than 45 days old.

The Base Services Charge is modeled per billing day at the workbook's income tiers: CARE, FERA/qualifying affordable housing, or standard. CARE and FERA volumetric discounts are estimates applied to comparable energy charges. Actual exemptions and account-specific line items may differ.

## Usage source

PG&E says residential electric usage can be downloaded in 15-minute intervals through Green Button Download My Data:

https://www.pge.com/en/save-energy-and-money/energy-usage-and-tips/understand-my-usage.html

The user must perform the account login and download. BillFit reads a local CSV/XML/JSON file and returns summaries rather than the full interval series.

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
