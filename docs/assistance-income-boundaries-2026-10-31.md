# Fractional assistance-income boundaries

Observed October 31, 2026. Base delivery `9bf1302c3f0fcb2a6e614da568c8b551b6d1da2e`; all examples are synthetic. This fixes an unsupported screening conclusion, not a tariff value, enrollment decision or monetary benefit.

## Problem and official-source limit

For a one-person household with supplied annual income of $43,280.50, the previous engine returned `fera.status: likely_eligible` while displaying a lower bound of $43,281. The [CPUC CARE/FERA table](https://www.cpuc.ca.gov/care/) still gives a $43,280 CARE maximum and $43,281 FERA minimum for households of one or two, effective June 1, 2026 through May 31, 2027. Its additional-household tables have the same one-dollar displayed boundary.

The [PG&E CARE page](https://www.pge.com/en/account/billing-and-assistance/financial-assistance/california-alternate-rates-for-energy-program.html) and [FERA eligibility page](https://www.pge.com/en/account/billing-and-assistance/financial-assistance/fera-eligibility.html) reviewed today require gross household income and refer to their income guidelines. The checked pages do not establish how fractional dollars in that displayed gap should be rounded. BillFit therefore preserves the uncertainty; it does not invent a utility rounding policy or automatically reject those households. This is an implementation decision based on incomplete rule precision, not a claim that the utility denies or approves these amounts.

## Result and compatibility

The same input now retains $43,280.50 exactly as supplied, returns
`fera.status: needs_official_confirmation`, `reason_code: FRACTIONAL_INCOME_BOUNDARY`
and `rounding_policy: unverified`, with `INCOME_BOUNDARY_CONFIRMATION` in
`human_gates`. The overall operation still returns `status: screened` because
individual pathways can be unresolved. The uncertain FERA path supplies no
`ASSISTANCE_APPLICATION` recommendation. It asks the user to confirm the boundary
with PG&E without rounding or changing their income.

At/below the CARE maximum, at the displayed FERA minimum, at the FERA maximum and
above it, existing screening outcomes remain unchanged. Recognized categorical
programs remain an independent CARE path; Medical Baseline remains independent
of income. Stale-data confirmation and outside-effective-window rejection
remain separate. Neither the CLI nor MCP accepts a caller-selected unapproved
snapshot or date. Tool descriptions and the skill tell consumers to preserve
the new uncertainty status rather than translate it into approval or denial.

Candidate review now includes cents immediately above/below both old and proposed
limits, plus .50/.99 inside each displayed CARE/FERA gap. Whole-dollar cases
remain. Proposed and baseline replays still use detached snapshots; all release
approval fields remain unset. Runtime-bound older review packages must be kept
as historical evidence and freshly prepared for this runtime, not edited to
match a new fingerprint.

No dependency, protocol, request-schema, supported account type, threshold or
packaged verification date changes. Consumers interpreting FERA status must
handle `needs_official_confirmation` and display its reason and gate. A source
inspection is recorded separately from approval to update all maintained rules.

## Verification

Eight methods frozen at `b459bcfe83fa8dfaf64ffbcca6dc9201fb106866` cover household
progressions, cent/subcent/adjacent floating-point values, categorical pathways,
medical need, stale/expired rules and candidate comparisons. Before the fix,
three methods passed; the remaining five produced 95 failing subcases and one
missing-scenario error. All eight pass unchanged after the fix in 0.030 seconds.
No model result is used to decide these assertions.

Actual local CLI and SDK checks exercise the uncertain result, ordinary edges,
invalid input and same-connection recovery in both already supported SDK modes
(`2026-07-28` and `legacy`). An initial new integration assertion expected the
calculator's direct-call error for a boolean income; inspection confirmed the
existing public schema rejects it first with `INVALID_ARGUMENTS`. The corrected
test preserves that rejection, and the unsuccessful first observation is kept.
No runtime validation was weakened. The two integration methods pass in 4.787
seconds. This is a real local SDK transport check, not a new Hermes/model-selected
workflow, utility call or customer enrollment.

The [verification receipt](../reports/income-boundaries-verification-20261031.json)
records terminal full-suite results, source hashes and the dated before/after
outputs. Prior [assistance-review evidence](assistance-rule-review-2026-10-31.md)
and its 168 whole-dollar scenarios remain historical observations.

Eight additional real CLI invocations compare four identical synthetic requests
against the unchanged base checkout and this implementation. The fractional-gap
result changes from `likely_eligible` to `needs_official_confirmation`; CARE
maximum, printed FERA minimum and categorical-path responses are otherwise
identical. [Requests and raw outputs](../reports/income-boundaries-workflow-20261031/fractional_gap-request.json)
are bound in the receipt. The explicitly labelled counterfactual comparison has
**288 scenarios**, retaining the original whole-dollar cases and adding 120
fractional cases; its 18 proposed threshold changes are synthetic and inactive.
The [source observation](../reports/income-boundaries-sources-20261031.json)
records successful bounded downloads and HTML hashes for all three checked
official pages. HTML hashes do not authenticate a rule interpretation.

The complete optional-profile suite passes **200 tests, zero skips, 45.016
seconds** on Windows Python 3.11.3. Existing rate calculations, DST/usage
boundaries, bill reconciliation, parser cancellation, image preparation and
real local SDK checks remain included. The elapsed time is one observation,
not evidence of a performance improvement over the earlier 190-test run.

## Run, limitations and rollback

Use the existing optional integration profiles for full SDK tests:

```text
python -m unittest discover -s plugins/billfit/tests -v
python plugins/billfit/skills/billfit/scripts/billfit_cli.py assistance --input-file request.json
```

For the synthetic boundary example, `request.json` contains:

```json
{"household_size": 1, "gross_annual_household_income": 43280.5}
```

No new configuration is needed. No models were called; no AI-quality, customer
savings or enrollment improvement is measured. Official fractional-income
interpretation, complete categorical-program coverage, exact utility rounding,
permissioned customer bills, native Windows OCR and independent first-use
acceptance remain open. Do not infer those outcomes from synthetic tests.

The branch is review-only; no installation, deployment, database migration,
snapshot activation or public release occurs. A reviewed revert restores the
earlier engine and its contradictory fractional-boundary conclusion. Keep the
new failed observations and complete prior data snapshots; no user data requires
migration. Publishing an exact version and operational rollout still need the
existing release approval.
