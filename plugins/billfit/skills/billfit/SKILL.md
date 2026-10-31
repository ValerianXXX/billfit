---
name: billfit
description: Compare supported PG&E residential electricity plans from Green Button CSV/XML or interval data, validate comparable bill components, and screen CARE, FERA, or Medical Baseline eligibility with versioned official rules. Use when a user asks whether their PG&E rate fits their usage, wants an E-1/E-TOU-C/E-TOU-D/EV2-A/E-ELEC comparison, supplies an electricity usage file, asks about PG&E low-income discounts, or needs a structured list of information and human actions still required.
---

# BillFit

BillFit supplies deterministic, source-dated calculations for a narrow PG&E MVP. Use its packaged calculator for every rate, threshold, eligibility, and bill-reconstruction calculation; do not reproduce those calculations with model reasoning.

## Calculator access

Prefer the `billfit_*` MCP tools when they are available. If the skill is installed without MCP, use the self-contained standard-library CLI in this skill folder.

Resolve `<skill-root>` as the directory containing this `SKILL.md`. Run:

```text
python <skill-root>/scripts/billfit_cli.py <operation> --input-file <request.json>
```

Supported operations are `scope`, `gates`, `parse`, `compare`, `validate`, `assistance`, and optional `extract-bill`. The request file must contain one JSON object whose keys match the corresponding function arguments. Use an empty object for `scope` and `gates`. Prefer a temporary JSON request file instead of interpolating user values into a shell command. The CLI returns one JSON object and never performs account or enrollment actions.

For a user-supplied PDF/image bill, `extract-bill` accepts `bill_file`. Every returned field is an unconfirmed candidate with source page/line/quote. Show conflicts and missing fields and obtain user confirmation before passing values to the calculator. Never treat total amount due as the comparable energy charge or total kWh as interval usage. PDF extraction needs optional pypdf; image OCR needs a trusted local Tesseract executable. Missing dependencies remain visible; do not upload bills as a fallback. On Windows the calculator also requires the packaged `tzdata` requirement.

Also show relevant `unresolved_fields` and `quality_flags`. OCR confidence is an uncalibrated engine signal, not a probability that an amount is correct; high confidence does not remove review. Do not repair comma groups, credits, ranges or plan suffixes with model guesses. Repeated pages remain separate evidence and are not additional charges. On `BILL_SOURCE_CHANGED`, have the user select the intended version; on time/output/parser errors, request a smaller readable export or manually verified fields.

Optional image preparation requires the `requirements-image-input.txt` profile in the server environment. For one image page, `ocr_rotation_degrees` specifies a clockwise correction after EXIF orientation; choose it from visual source inspection, never from a desired amount. `ocr_deskew: true` requests conservative local small-angle correction. Both default off. Original bytes remain unchanged; do not iterate angles to maximize extracted fields. Ambiguous deskew applies no correction and remains visible. If preparation fails or layout remains uncertain, keep the original and use a readable copy or manually verified fields; do not upload it as a fallback.

Show the returned `image_preparation` and `IMAGE_PREPARATION_REQUIRES_REVIEW` information. Prepared-image evidence uses original **encoded** pixel coordinates, before EXIF display rotation; a client overlay must account for that. Word polygons and derived-image boxes are review aids, not proof that text or numbers are correct. A manually corrected quarter-turn on synthetic development samples does not establish automatic orientation detection or real-bill accuracy. PDF preparation and multipage TIFF preparation are unsupported; export the intended page as an image. Existing calculator and confirmation gates still apply.

The optional `--sdk` server admits two bill extractions per instance. On `BILL_PARSER_BUSY`, retain the supplied path and wait for an active extraction to complete or be cancelled; do not loop or create another server to bypass the limit. A cancelled call supplies no confirmed fields or successful result. The default synchronous legacy shim does not provide cooperative MCP cancellation. CLI tools retain their existing behavior.

Use file paths exactly as supplied by the user or execution client, including relative filenames. Never invent a directory such as `/mnt/data` or convert a filename into an assumed absolute path. If no accessible path was provided, request that missing path; if a read fails, report it instead of guessing other files. Local parsing does not mean a cloud model conversation is local: the host may send returned field values, evidence snippets and calculation results to its configured model provider.

## Safety and scope

- Start with `billfit_get_supported_scope` when the account type is uncertain.
- Fail closed for solar/NEM/net export, CCA/Direct Access, master-metered accounts, gas, or unsupported plans.
- Never ask for or accept a utility password, SSN, tax return, pay stub, medical record, or clinician signature.
- Never log in, change a rate plan, submit an assistance application, or certify a medical condition.
- Treat every result as a screening or comparable-charge estimate. The cited official tariff and the utility's decision control.
- Preserve unknown facts as explicit human gates. Do not invent a baseline territory, heating type, technology, income, current plan, or assistance status.

Maintenance review packages are not calculator activation or release approval.
`REVIEW_REQUIRED` with matching hashes/replayed calculations still needs source
mapping, effective-date review and owner approval of an exact published version.
Do not edit a package's approval/gates or use synthetic counterfactual rates for
customer advice. The ordinary calculator continues to use its packaged rules;
no MCP argument selects an unapproved tariff snapshot.

## Workflow

### 1. Establish the smallest valid scope

Confirm or record as unknown:

- PG&E individually metered residential bundled electric service
- no solar, NEM, or net export
- no CCA or Direct Access generation provider
- current plan, if switch savings are requested

If a disqualifying fact is true, explain the exclusion and stop the rate calculation. Assistance screening may still be run independently.

### 2. Obtain usage without taking over the account

Prefer a user-provided Green Button CSV or XML file. If none is available:

1. Call `billfit_list_human_gates`.
2. Explain that the user must sign in to PG&E and download Green Button data themselves.
3. Leave `ACCOUNT_LOGIN` and `REAL_USAGE_FILE` waiting; continue with assistance screening or scope explanation if requested.

When a file is supplied, call `billfit_parse_usage_file` or run the CLI `parse` operation first. Summarize date range, total kWh, coverage, interval size, and warnings without echoing full interval data.

Preserve interval errors and input assumptions. Identical repeated records retain one value with a warning; conflicting duplicates, overlaps, unknown units and ambiguous local daylight-saving times require corrected source data. Do not invent offsets, silently discard a conflicting row or add repeated usage. A generic CSV `duration` column needs explicit minutes/seconds units. Multiple ESPI reading types or usage points need a supported source mapping; do not combine accounts.

### 3. Collect only facts that materially change the calculation

For E-1 or E-TOU-C, obtain baseline territory P–Z and `basic` versus `all_electric` service. If absent, leave `BASELINE_INFO` waiting; still calculate plans that do not require baseline when possible.

For EV2-A or E-ELEC, obtain the applicable technology:

- `electric_vehicle`
- `battery_storage`
- `heat_pump_water`
- `heat_pump_space`

If unknown, leave `TECHNOLOGY_ELIGIBILITY` waiting. Do not assume eligibility from high usage or time-of-day patterns.

### 4. Compare and verify

Call `billfit_compare_rate_plans` or run the CLI `compare` operation with the same file path and every confirmed fact. Report:

- data-quality level and covered dates
- rate snapshot effective date and official source
- calculated plan ranking and comparable annualized totals
- estimated switch savings only when the current plan was supplied and calculated
- excluded bill components and all returned human gates

When `withheld_pending_usage_quality` or `USAGE_QUALITY_REVIEW` is returned, describe the calculation as illustrative and preserve the missing-data requirement. Do not promote a short, gappy, coarse or inferred interval series into an established annual saving. Even a `validated` bill result only reconciles comparable components; check `validation_scope`, `usage_evidence_status` and the remaining gates before describing its evidential strength.

If a bill is available, ask only for the line-item energy charge and Base Services Charge, then call `billfit_validate_bill` or run the CLI `validate` operation. Do not validate against the whole amount due. If the reconstruction is outside tolerance, withhold a switching recommendation until the mismatch is explained.

### 5. Screen assistance separately

Call `billfit_screen_assistance` or run the CLI `assistance` operation with household size and, if the user chooses to provide it, gross annual household income or names of qualifying public programs. Medical Baseline needs only a yes/no/unknown indication at this stage.

- Say “likely eligible,” “likely not eligible by the supplied path,” or “needs information,” matching the tool result.
- Do not say “approved” or “ineligible” as a final determination.
- If CARE or FERA looks likely, leave `ASSISTANCE_APPLICATION` for the user.
- If a medical need is indicated, leave `MEDICAL_CERTIFICATION` for the user and practitioner.

### 6. Present a compact result

Use this order:

1. Bottom line
2. What BillFit calculated and the source date
3. Important exclusions or uncertainty
4. Human actions still waiting

Keep account-download instructions separate from analytical results. If the user is unavailable, finish every non-interactive calculation and preserve the waiting gates without repeatedly asking.

## Calculator routing

- Scope or exclusions: `billfit_get_supported_scope` or CLI `scope`
- Pending human actions: `billfit_list_human_gates` or CLI `gates`
- File quality and parsing: `billfit_parse_usage_file` or CLI `parse`
- Plan comparison: `billfit_compare_rate_plans` or CLI `compare`
- Bill-component reconciliation: `billfit_validate_bill` or CLI `validate`
- CARE/FERA/Medical Baseline screening: `billfit_screen_assistance` or CLI `assistance`

Read [references/sources-and-limitations.md](references/sources-and-limitations.md) when explaining official sources, supported rate-plan rules, privacy boundaries, or why a result is not a final utility decision.
