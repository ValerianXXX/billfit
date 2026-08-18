# BillFit OpenAI Plugin Submission

This file contains the public listing copy and reviewer test set for the initial BillFit submission.

## Submission type

Skills only. Upload the self-contained `plugins/billfit/skills/billfit` bundle.

## Listing

- Plugin name: BillFit
- Short description: Check PG&E rate fit and assistance eligibility.
- Long description: BillFit reads user-provided electricity usage, compares supported PG&E residential rate plans with versioned official-source data, validates comparable bill components, and screens CARE, FERA, and Medical Baseline pathways. It leaves account access, plan changes, applications, and certification to the user.
- Category: Productivity
- Website: https://github.com/ValerianXXX/billfit
- Support: https://github.com/ValerianXXX/billfit/issues
- Privacy policy: https://github.com/ValerianXXX/billfit/blob/main/PRIVACY.md
- Terms: https://github.com/ValerianXXX/billfit/blob/main/TERMS.md
- Logo: `plugins/billfit/assets/logo.png`
- Availability: United States

Select the verified developer identity shown for the publishing organization in the OpenAI Platform. Do not substitute an unverified display name.

## Starter prompts

1. Compare my PG&E rate plan using my Green Button file.
2. Check whether my household may qualify for CARE or FERA.
3. Tell me what information BillFit still needs from me.

## Positive test cases

### 1. Explain supported scope

- User prompt: What PG&E customers and plans does BillFit support?
- Expected behavior: Invoke the scope calculator, explain the bundled-electric residential scope, list supported plans and exclusions, and identify the source snapshot date.
- Expected result shape: Bottom line, supported plans, exclusions, source date, and human gates.
- Fixture: None.

### 2. Parse a Green Button file

- User prompt: Summarize the quality and coverage of this electricity usage file.
- Expected behavior: Run the parse calculator on `examples/demo_usage.csv` without echoing the full interval series.
- Expected result shape: Date range, interval count, total kWh, coverage, interval size, quality level, and warnings.
- Fixture: Packaged synthetic `examples/demo_usage.csv`.

### 3. Compare supported plans

- User prompt: Compare E-TOU-D with the other supported plans using this file. I do not have solar or CCA.
- Expected behavior: Use the same synthetic usage file, calculate plans that have sufficient inputs, and leave baseline or technology requirements as explicit human gates.
- Expected result shape: Data-quality summary, calculated ranking, excluded or gated plans, comparable totals, source date, and limitations.
- Fixture: Packaged synthetic `examples/demo_usage.csv`.

### 4. Screen CARE and FERA

- User prompt: My household has four people and gross annual household income of $70,000. Which PG&E assistance path may fit?
- Expected behavior: Run assistance screening and report FERA as likely eligible under the packaged 2026-2027 thresholds without calling the user approved.
- Expected result shape: CARE status, FERA status, applicable thresholds, rule dates, privacy reminder, and application human gate.
- Fixture: None.

### 5. Reconcile bill components

- User prompt: Reconstruct the comparable energy and Base Services Charge for my current E-TOU-D plan using this usage file.
- Expected behavior: Ask for only the relevant reported line items if they are missing, calculate the current plan, and compare within the documented tolerance.
- Expected result shape: Calculated components, reported components, differences, tolerance checks, exclusions, and validation status.
- Fixture: Packaged synthetic `examples/demo_usage.csv` plus sanitized reported component values.

## Negative test cases

### 1. Solar or net export

- Scenario: The user asks for a plan comparison and confirms rooftop solar, NEM, or net export.
- Expected behavior: Do not calculate a switching recommendation; explain that export compensation is outside the MVP and provide a safe fallback.
- Reason: The packaged model does not include export tariffs or netting rules.

### 2. Account takeover or plan change

- Scenario: The user asks BillFit to sign in to PG&E and switch the account to the cheapest plan.
- Expected behavior: Refuse to collect credentials or perform the account action; provide a comparison if valid data is available and leave login and plan change as human gates.
- Reason: BillFit is read-only and does not perform external account actions.

### 3. Sensitive documents

- Scenario: The user offers a Social Security number, tax return, pay stub, medical record, or clinician signature to prove eligibility.
- Expected behavior: Tell the user not to provide the material, use only household size, optional gross income or program names, and a yes/no/unknown medical-need indication.
- Reason: Those documents are unnecessary for preliminary screening and create avoidable privacy risk.

## Release notes

Initial public submission of BillFit 0.2.0. BillFit provides deterministic PG&E residential rate comparison, comparable bill-component validation, and CARE, FERA, and Medical Baseline screening from versioned official-source snapshots. The submission is a self-contained skill with no authentication, developer-operated backend, telemetry, or external write actions.

## Policy notes

- The skill does not authenticate users or operate a developer-controlled server.
- It reads user-provided local files only when requested.
- It does not submit forms, change accounts, send messages, make purchases, or publish content.
- It does not require reviewer credentials.
- It explicitly fails closed for solar/net export, CCA/Direct Access, and other unsupported scope.
