# Bill reconciliation: arithmetic, period evidence and remaining limits

This draft adds explicit statement-period evidence and fixes a decimal tolerance
boundary. It does not change tariff numbers, activate data, certify a customer
bill or broaden account support. The predecessor is draft #9 at
`2847b4c8deb40485c5e1400347898567b50c7135`.

## Reproduced problems

- The old calculator returned `validated` for a matching charge supported by
  only one hour of readings. It returned a usage-review gate too, but consumers
  following the top-level status could mistake an arithmetic match for adequate
  bill evidence.
- A month with one missing hour still met the old 95% quality threshold and
  could return annual savings. Missing first/last records could not be detected
  against a statement because the API had no explicit bill-period input.
- A stale snapshot replaced the recommendation status but retained numeric
  annual-savings fields from the earlier recommendation.
- A calculated $4.40 compared with a reported $2.40 produced a displayed $2.00
  difference and $2.00 tolerance, yet `within_tolerance` was false. Binary
  subtraction was slightly greater than two. Reported subcent amounts were
  silently rounded in displayed checks.

These are synthetic reproductions, not claims of a deployed customer incident.

## Behavior and API

`billfit_validate_bill` and CLI `validate` accept an optional `billing_period`:

```json
{
  "start_date": "2026-07-06",
  "end_date_exclusive": "2026-07-07"
}
```

These are Pacific calendar dates. This example covers one local calendar day.
Confirm the statement's date convention before converting an inclusive printed
end to an exclusive end. Neither OCR nor the interval series supplies an
automatic confirmation. Unknown, compact, reversed, extra-key or over-1,098-day
periods are rejected with `INVALID_BILLING_PERIOD`.

The response separates:

| Field | Meaning |
| --- | --- |
| `arithmetic_status` | Supplied comparable amounts match, mismatch, or were not supplied |
| `billing_period` | Declared dates, calendar days, actual elapsed minutes, missing minutes, extra intervals and tariff-window coverage |
| `required_reviews` | Unresolved date, usage-assumption or rate-verification requirements |
| `status` | `validated` only for a component match with adequate period/rate evidence; otherwise review, mismatch or missing information |

A missing/extra interval, inferred unit/duration, coarse interval or unavailable
applicable rate prevents validated status. A complete, explicit short final bill
can reconcile: the 28-day switching threshold is not a minimum bill length.
Spring/fall calendar days retain their 23/25 elapsed hours. The daily Base
Services Charge uses declared calendar days when dates are supplied; otherwise
the old usage-span estimate remains explicitly labeled. All supplied usage is
still priced for diagnostics. Extra records are not silently clipped, missing
usage is not zero-filled, and baseline allowances do not invent missing energy.

Any detected interior gap now prevents switching-savings fields, even if the
descriptive quality grade remains `good`. Stale recommendations omit numeric
savings instead of only changing their status. Per-plan annualized amounts remain
illustrations of the supplied pattern, not established annual savings.

Money reconciliation uses decimal cents with the existing tolerance rule:
`max($2.00, reported amount * 2%)`. The check uses the unrounded tolerance;
`tolerance_unrounded` explains cases where the displayed tolerance rounds up.
Reported amounts must be finite nonnegative cents, at most $1e15 (a calculator
limit, not a utility rule). Subcent input must be clarified, not silently rounded.
The decimal context is isolated from host-library settings.

This changes comparison of already priced components. It does **not** replace
the pricing engine's arithmetic or establish PG&E's exact line-item rounding.
`pricing_rounding_certified` remains false. The previous five-plan/two-season
pricing regression is preserved.

## Sources and boundaries

The [PG&E electric-rate page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html)
and [Electric Rule 9, section A](https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_RULES_9.pdf)
were read on October 31, 2026. Rule 9 describes billing periods and use of daily
equivalent charges. The explicit-period API is BillFit's implementation choice;
it does not claim every statement uses the same printed end-date convention.
The [preceding source observation](../reports/tariff-review-source-observation-20261031.json)
retains the byte-identical official workbook check. Packaged values, effective
dates and `verified_on` stay unchanged.

Current-rate counterfactual comparison and historical bill reconstruction are
different operations. A bill beginning before the packaged rate's effective
date, or ending after a known effective end, requires the appropriate historical
snapshot. BillFit does not extrapolate that snapshot into a validated bill.
This release still has one active packaged tariff snapshot; automatic historic
selection and cross-version billing remain unimplemented.

## Evidence and retained failures

The unchanged predecessor passed 157 full tests and hosted CI. Fifteen new
methods were committed before implementation. Initially they produced eight
failing assertions/subtests and 16 errors, including the unsupported period
parameter. The first implementation left one failure: an authored expected
31-day charge of $24.39 was wrong. The unchanged source is $0.79343/day, so
31 days is $24.59633, displayed $24.60. That single expected value was corrected;
the original test commit and both failure logs remain. Do not describe all 15
as an unchanged frozen set.

The corrected 15 methods plus six integration methods pass (21 total, 10.895
seconds). Two old one-hour tests now require `needs_review`, retained arithmetic
agreement and review evidence; none was deleted or made less strict. Actual CLI
and both existing SDK modes exercise declared dates, malformed/subcent errors
and successful continuation on the same SDK connection. These are local
component/client observations on synthetic inputs, not Hermes/model or customer
acceptance. The full Windows Python 3.11.3 optional-profile suite passes 178 tests
with no skips in 62.946 seconds, including the unchanged seasonal pricing
regression. The separate seven-case CLI replay passes all eight checks, including
unchanged packaged source bytes. See the
[verification receipt](../reports/bill-reconciliation-verification-20261031.json)
for hashes and original logs. A manual Windows `python -S` check failed because
it hides the required installed `tzdata`; supported normal Windows execution and
dependency checks pass. This does not establish a package-free Windows runtime.

## Run and replay

No new dependency, configuration, account or model is required. From the checkout:

```shell
python -m unittest discover -s plugins/billfit/tests -p "test_bill_reconciliation*.py" -v
python scripts/verify-bill-reconciliation.py --output-root reports/my-reconciliation-replay
python plugins/billfit/skills/billfit/scripts/billfit_cli.py validate --input-file plugins/billfit/skills/billfit/examples/synthetic-bill-reconciliation.json
```

The replay command needs Git history containing the fixed predecessor. It runs
seven declared synthetic requests through both CLIs (14 invocations), retains
old unsupported-parameter errors, and saves observations in a fresh directory.
It uses no arbitrary customer input. The example covers 24 kWh on July 6:
21 off-peak kWh at $0.34212 plus three peak kWh at $0.47708 = $8.61576, displayed
$8.62; daily Base Services Charge $0.79343 displays $0.79. This is a component
example, not an actual account bill. Freshness is checked at execution time, so
later execution can correctly require new rate verification.

Existing callers may omit `billing_period` and receive useful arithmetic, but
must accept `needs_review` instead of assuming a match means `validated`.
Update consumers to retain `required_reviews` and `human_gates`. No user data or
database migration is involved. Review packages made with older runtime hashes
remain historical evidence; do not rewrite their hashes to make current replay
pass. Prepare a new package after reviewing the changed runtime.

Rollback is an ordinary source revert to the predecessor, with the explicit
warning that it restores the old evidence and tolerance defects. Keep input
records, observations and both source snapshots; no tariff activation or
production rollback occurred. Real customer reconciliation, exact utility
rounding, independent human acceptance, and tariff publication approval remain
open.
