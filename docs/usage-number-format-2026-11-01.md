# Usage number validation

Observed 1 November 2026. This is an input-correctness repair in the development
checkout, not a tariff update, customer study or published plugin release.

## Reproduced problem and change

The shared usage adapter removed every comma and dollar sign before converting
to a number. Consequently `1,23` became 123 kWh, `1$2` became 12 kWh, and `6,0`
could become a 60-minute interval. Python also accepted underscores in text.
Separately, the CSV adapter paired cells with headers and silently discarded any
surplus cell, so an unquoted grouped number could be truncated to its first group.

The adapter now checks a bounded numeric grammar before removing valid thousands
separators. The same validation covers inline intervals, JSON files, CSV and
ESPI values/durations. Nonzero text that converts to floating-point zero is
rejected. CSV records wider than the header return `CSV_ROW_WIDTH_MISMATCH`,
including an extra empty trailing cell. Errors retain the existing domain error
format and do not echo supplied values. No partial parsed result is returned.

Valid decimals, exponent notation, complete comma groups and existing parenthesized
negative values retain their meaning. Missing optional duration cells keep the
existing inference warning and review requirement. Negative usage still blocks
rate comparison as unsupported net export. Originals are read-only.

## Fixed before/after evidence

Base: `d9d2a079312cf9948b4f5fe4084629ebf41f5cf2` (draft #14).
The [protocol](../evaluations/usage-number-format-v1/protocol.json), fixture,
nine test methods and CLI evaluator were committed in `00c7180` before the
runtime change `97a8046`. Neither labels nor case counts changed afterward.

| Same actual CLI requests | Before | After |
| --- | ---: | ---: |
| Invalid inputs rejected with the expected error and no values | 12 / 53 | 53 / 53 |
| Valid inputs retaining their energy and duration | 37 / 37 | 37 / 37 |
| Source files unchanged | 90 / 90 | 90 / 90 |
| Sum of process elapsed time | 25.476 s | 26.162 s |

The 53 invalid cases include malformed values, explicit duration problems,
surplus cells, existing nonfinite/type rejections and XML adapters. These are
exposed synthetic development cases. The elapsed times are one workstation
observation under concurrent load, not a latency or cost improvement claim.

The frozen tests initially reported 48 failed assertions/subtests and two
SDK-wrapped assertion errors; two methods already passed. All nine pass after
the change. Actual MCP SDK 2.3.0 clients reject an invalid CSV, then parse a valid
quoted value on the same connection in both existing `2026-07-28` and `legacy`
modes. This is a real local interface check, not Hermes choosing a tool or a
model completing a customer task.

The complete optional-profile suite passes **223 tests, zero skips, 56.224 s**
on Windows / Python 3.11.3. It includes prior deterministic calculations, DST,
duplicate handling, rule-review isolation, image/PDF parsing and cancellation.
The unchanged base's 214-test local/hosted success is prior evidence, not rerun
under this milestone's name. Dependencies pass their consistency check; none
were added. Final-delivery hosted CI is recorded separately in the draft PR.

The [receipt and retained observations](../reports/usage-number-format-2026-11-01/verification.json)
bind code, fixture, evaluator, all CLI rows and original failure logs. This work
made zero model calls and used no customer records. It proves neither a model
quality gain nor financial benefit.

## Use and recovery

Use the existing installed requirements and exact supplied file path:

```text
python plugins/billfit/skills/billfit/scripts/billfit_cli.py parse --input-file request.json
python -m unittest discover -s plugins/billfit/tests -p test_usage_number_format.py -v
python scripts/verify-usage-number-format.py --output reports/new-number-observation.json
```

The parse request is a JSON object with `usage_file` pointing to the intended
local CSV, XML or JSON. The evaluator creates only fixed synthetic temporary
files, accepts an optional `--repository` for the unchanged comparison checkout,
and refuses to overwrite an observation. It requires no model or credentials.

- Supported examples: `1.25`, `.25`, `1.`, `1.25e-3`, `1,234.50` and `(1.25)`.
  Tokens are at most 128 characters. Commas are thousands separators only.
- In CSV, quote a grouped number as one cell, for example `"1,234.50"`.
- On a numeric or row-width error, keep the original. Re-export or verify a
  separate corrected copy against it; do not ask a model to guess the value.
- This does not add locale detection, arbitrary precision or canonical ESPI
  schema validation. A client that already turned a tiny numeric token into
  zero before sending it cannot have its lost source spelling reconstructed.

No `.env`, SDK, model, protocol or deployment configuration changes are needed.
Both rate and assistance JSON snapshots, their verification dates and the
existing tariff calendar are byte-identical to the base.

## Remaining source questions and rollout

A separate official-source follow-up on 1 November inspected the current
[E-TOU-D tariff, sheet 4](https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf)
and [PG&E TOU holiday page](https://www.pge.com/tariffs/en/rate-information/tou-holidays.html).
The tariff ties its holiday dates to legal observance. The latter page explicitly
describes non-residential calendars, including Saturday handling, and also makes
a general residential statement that does not match this tariff's holiday
exception. That page is insufficient to replace E-TOU-D's calendar unconditionally.
No calendar or current-rate certification follows from this input repair; the
Saturday-observance interpretation remains a source-review question. This
partial check does not re-date the packaged October 27 tariff verification.

Exact utility rounding, complete historical tariffs, real bills and independent
user acceptance remain outside this evidence. The existing human confirmation
and unsupported-account boundaries are unchanged.

No data migration or production action is required. Review the draft before any
release. A normal reviewed code revert restores the previous parser, including
its known silent-normalization risk; retained source files and reports must be
preserved. Rule-review bundles already bind the usage module's hash, so create a
new review bundle after a runtime change rather than relabeling historical ones.
