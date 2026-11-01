# Green Button reading meaning and quality

Observed 1 November 2026. Draft development change; no rate activation, account
action, dependency addition or production migration.

BillFit previously checked the energy unit but ignored declared direction and
accumulation. Positive exported energy or a cumulative register could therefore
reach the consumption calculator. Missing meaning and estimated quality also
disappeared from the review decision. Numeric syntax validation alone did not
repair this problem.

`billfit_espi.py` now keeps this input interpretation separate from tariff
arithmetic. The usage adapter validates it before returning intervals; parsing,
comparison and reconciliation share the review decision. Original bytes,
existing interval validation and all rate/assistance snapshots are preserved.

## Supported input profile

| Declaration | Required meaning or behavior |
| --- | --- |
| `accumulationBehaviour` | `4`, incremental interval energy |
| `commodity` | `1`, metered secondary electricity |
| `flowDirection` | `1`, forward/import; a positive number does not imply import |
| `kind` | `12`, energy |
| `dataQualifier` | Ordinary `12`, not-applicable `0`, or absent; other qualifiers are rejected |
| `uom`, `powerOfTenMultiplier` | Existing supported energy units/scaling; duplicate or nested declarations are rejected |
| Service category, if supplied | Electricity `0`; gas and other services are rejected |
| Reading streams | At most one MeterReading, one UsagePoint and exactly one ReadingType |
| Quality | Interval flags override the default; every supplied flag remains relevant |

Missing or unspecified core meaning keeps a legacy file readable with
`ESPI_READING_METADATA_REVIEW`. Known incompatible declarations return
`UNSUPPORTED_ESPI_READING_TYPE`. Multiple streams return
`MULTIPLE_ESPI_METER_READINGS`. Malformed, duplicate, nested or foreign-namespace
meaning fields return explicit metadata errors instead of selecting the first.

Quality codes `0` (valid) and `19` (revenue quality) do not add a new review.
Unspecified quality and other codes add `ESPI_READING_QUALITY_REVIEW`, including
estimated, forecast, normalized, manually edited and otherwise qualified values.
This is BillFit's conservative review policy, not a claim that every other code
is invalid. A valid default does not hide an interval's estimate; conversely an
explicit valid interval can override an estimated default. Mixed flags such as
revenue quality plus weather normalization retain review.

Both warnings produce `USAGE_QUALITY_REVIEW`. Comparison withholds switching
savings even for 28 complete days; bill reconciliation remains `needs_review`
even when supplied components arithmetically match. Per-plan amounts are only
illustrative until the input basis is resolved. Coverage grade `good` describes
time coverage and does not certify reading meaning or quality.

This is a bounded input profile, not complete ESPI/XSD certification, a general
Atom-link/multiple-meter resolver or a guarantee of source authenticity.
Unqualified legacy XML namespace support remains. Existing supported non-solar, individually
metered PG&E bundled-residential scope is unchanged.

## Run and recover

From this development checkout, after the existing requirements are installed:

```shell
python plugins/billfit/skills/billfit/scripts/billfit_cli.py parse --input-file plugins/billfit/skills/billfit/examples/synthetic-espi-import.json
python plugins/billfit/skills/billfit/scripts/billfit_cli.py parse --input-file plugins/billfit/skills/billfit/examples/synthetic-espi-review.json
python plugins/billfit/skills/billfit/scripts/billfit_cli.py parse --input-file plugins/billfit/skills/billfit/examples/synthetic-espi-export.json
```

These deliberately tiny synthetic files demonstrate accepted import, unresolved
meaning and rejected positive export; they cannot support switching advice.
The rejected example exits with status 2 and a structured error. CLI and MCP
arguments/settings are unchanged. No credentials, cloud fallback or model are
required. The SDK server remains optional; the legacy shim retains its existing
synchronous behavior.

Keep the source. Obtain a confirmed utility export of the intended incremental
import stream when the meaning is incompatible or unclear. Do not relabel an
export, subtract cumulative values without a supported method, erase quality
flags, combine meters or convert to unlabelled JSON to bypass review. Preserve
the existing user-confirmation and account-action boundaries.

## Frozen comparison and validation

The [protocol](espi-semantics-protocol-2026-11-01.md), 73-case matrix, fixture
generator and six API/SDK methods were committed before the implementation.
The CLI evaluator was also committed before the runtime change. The unchanged
cases cover incompatible quantities, absent meaning, duplicate and nested
metadata, namespaces, service/stream boundaries, quality precedence and valid
scaling. Initial failing observations are retained.

| Actual CLI outcome | Before | After |
| --- | ---: | ---: |
| Unsupported/ambiguous inputs correctly rejected | 0/38 | 38/38 |
| Unresolved meaning/quality visibly held for review | 0/20 | 20/20 |
| Supported controls and kWh preserved | 15/15 | 15/15 |

All 73 source files remain byte-identical in each arm. Single-workstation totals
are 19.922 seconds before and 20.469 seconds after, not a performance claim.
Actual SDK 2.3.0 calls exercise the existing `2026-07-28` and `legacy` client
modes: reject positive export, then parse a valid file on the same connection.
This is real local transport/file integration, not a new model-selected Hermes
trial, customer workflow or independent-human acceptance.

Run the frozen comparison with a **new** output path; previous observations are
never overwritten:

```shell
python scripts/verify-espi-semantics.py --output /path/to/new-espi-observation.json
python -m unittest discover -s plugins/billfit/tests -v
```

The evaluator records individual failures rather than treating its process exit
as the acceptance verdict; inspect every `summary` category. The tests enforce
the contracts. [Verification receipt](../reports/espi-semantics-2026-11-01/verification.json)
records baseline, complete-suite results, hashes, versions and limits. No new
model calls or model-quality/cost improvement is claimed. All development
samples are exposed synthetic cases, not an untouched generalization set.

The baseline suite passes 223 tests (55.570 seconds); the complete updated native
Windows/Python 3.11.3 optional-profile suite passes 229 (58.958 seconds), with
zero skips. The original six-method run had 64 failed assertions/subtests and
two SDK-wrapped assertion errors; all six now pass unchanged. Hosted acceptance
is recorded separately after the delivery commit is pushed.

## Sources, remaining limits and rollback

Official references checked on 1 November 2026:

- [Green Button Alliance schema view](https://dev.greenbuttonalliance.org/espiusecase.html),
  visibly version 3.3.20190408, supplies the code meanings. This is not asserted
  to be the latest schema revision. Its reverse/export direction can be positive.
- [Reading quality](https://www.greenbuttonalliance.org/accuracy) explains default
  versus interval quality and multiple flags. The profile accepts the structured
  schema form and scalar form shown in that official example.
- [Multiplier example](https://www.greenbuttonalliance.org/poweroftenmultiplier)
  illustrates incremental import energy and Wh-based scaling.

No external source code was copied. These input references do not certify PG&E
amounts or refresh the packaged tariff verification date. Exact utility rounding,
residential Saturday holiday-observance interpretation, complete historical
tariffs, customer bills and independent-user acceptance remain unresolved.

No storage schema or configuration migration. Roll back only through a reviewed
code revert, retaining originals and observations; the prior parser admits the
documented unsupported inputs again. Regenerate runtime-bound maintenance review
bundles after changing runtime bytes. Neither this change nor rollback approves
a candidate rate, plan switch, release or deployment.
