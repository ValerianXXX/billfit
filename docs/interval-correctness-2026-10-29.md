# Interval correctness and usage evidence — October 29, 2026

Baseline `6e476b2ae1b38e0c0c9359842fba71ef32d41292` is the unmerged rate/input branch in PR #3. It was clean and matched the remote before this work. The original 34 tests passed. This milestone changes local parsing and deterministic accounting, without changing tariff numbers, assistance thresholds, source effective dates or the packaged October 27 verification date.

## Why refactor

The old parser added repeated readings, keyed times by local wall-clock datetimes and applied the first XML unit declaration to the whole file. It could accept non-finite values, infer explicit invalid durations and silently discard a row with usage but no timestamp. A 600-minute CSV duration could become ten minutes because units were guessed from magnitude. Splitting a 16:59 interval into 15-minute chunks could allocate post-17:00 energy to the preceding tariff period.

`billfit_usage.py` now owns all local input adapters, canonical validation and elapsed-time accounting. `billfit_errors.py` provides the same domain exception used by the calculator, CLI and MCP. Existing public operations remain in `billfit_core.py`; the refactor is inside the self-contained Skill bundle and adds no dependency.

- Each adapter validates finite, nonboolean values and explicit units/durations before returning the same ordered interval representation.
- UTC instants define identity, ordering and duration. Explicit `01:15-07:00` and `01:15-08:00` remain distinct. Ambiguous or nonexistent offset-free Pacific times require correction.
- Identical repeats retain one reading with a count warning. Conflicts and overlaps fail closed. No multi-account aggregation is inferred.
- Missing duration remains a disclosed inference with switching guidance withheld. An explicitly invalid duration cannot be repaired by fallback. CSV minutes and seconds are named, not guessed.
- XML requires one ReadingType and no more than one UsagePoint. Richer ESPI relationship mapping remains unsupported rather than silently using the first unit.
- Energy splitting respects actual UTC clock boundaries and conserves elapsed minutes/kWh, using Pacific local time for the tariff. It still assumes uniform power within each interval. Daily baseline fractions use the actual 23/24/25-hour local day.

Insufficient, inferred or coarse data can still produce illustrative component totals, but cannot establish annual switching savings. A separate `USAGE_QUALITY_REVIEW` gate persists even when the supplied bill components match arithmetically. `validated` retains its existing component-reconciliation meaning, now made explicit by `validation_scope` and `usage_evidence_status`; it does not validate an entire bill or clear the account-action boundary. Non-finite, boolean and negative comparable bill amounts are rejected.

## Frozen observations

The [28-case protocol](../plugins/billfit/skills/billfit/data/verification/interval-protocol-2026-10-29.json) and original tests were committed at `7c16c37` before product changes. The [initial observation](../plugins/billfit/skills/billfit/data/verification/interval-before-2026-10-29.json) contains **1 pass, 26 failures and 1 error**. The original exception for an infinite duration is preserved. The same 28 test bodies pass after the refactor; see the [final observation](../plugins/billfit/skills/billfit/data/verification/interval-after-2026-10-29.json). No frozen input, expected result or denominator changed.

| Boundary | Result after change |
| --- | --- |
| Repeated, conflicting and overlapping readings | One retained value or explicit rejection |
| DST fold/gap, elapsed ends and full calendar days | Distinct instants, correct elapsed coverage and daily fraction |
| Tariff boundary at a non-quarter-hour start | Energy conserved on the proper side of the clock boundary |
| Units, duration units, missing timestamps, invalid numbers | Explicit error or disclosed inference |
| Multiple XML reading types and missing interval fields | Rejected without guessing |
| Sparse usage | Illustrative calculation, no established switching savings |

Ten additional review/integration tests cover malformed bill amounts, arithmetic versus evidence sufficiency, an adequate synthetic month, energy conservation, explicit seconds/endpoints, multi-meter exclusion, resource/overflow handling and actual SDK error/recovery. An initial additional-test run exposed the amount/quality problems; its subtest assertion scope also produced a secondary fixture error. That scope was corrected without changing the expected behavior. It is separate from the unchanged frozen 28-case set, and the initial log hash is retained.

Final local suite: **72 passed, no skips**. The previous winter/summer five-plan result objects match the committed October 27 observations exactly; this establishes no regression on those regular-hour fixtures, not universal tariff correctness. Real subprocess tests exercised both existing SDK protocol modes, including conflict errors, continued successful DST comparison and invalid amount rejection. CLI examples use actual files and processes. No new model call or real customer data was used, and no general AI quality/latency/cost benefit is claimed. The earlier Hermes model runs remain dated historical observations, not reclassified as tests of this revision.

The [verification receipt](../plugins/billfit/skills/billfit/data/verification/interval-verification-2026-10-29.json) records four actual CLI results, unchanged snapshot hashes, environment, source hashes and original/final log hashes. These are dated observations against the current packaged source versions; future tariff/rule updates require a new dated comparison rather than rewriting this result.

## Source review

On October 29, the [PG&E rate page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html) still listed March 1, 2026 to present, and the [CPUC CARE/FERA page](https://www.cpuc.ca.gov/care/) still displayed June 1, 2026–May 31, 2027. This was a page-content review, not a new workbook download/hash verification or a new tariff-cell audit. It does not reset `verified_on`, activate a candidate or prove future rates. The existing source-check/candidate-review path and stale-data gate remain in force.

## Reproduce

Use the existing Python environment and optional MCP profile if testing that transport:

```sh
python -m pip install -r plugins/billfit/requirements.txt
python -m pip install -r plugins/billfit/requirements-agent.txt
python -m pip install -r plugins/billfit/requirements-bill-input.txt
python -m unittest discover -s plugins/billfit/tests -v
python plugins/billfit/skills/billfit/scripts/billfit_cli.py compare --input-file plugins/billfit/skills/billfit/examples/synthetic-dst-compare.json
```

The example contains two synthetic repeated-hour readings and intentionally lacks a sufficient observation period. No credentials, real account data, persistent Hermes configuration or paid model endpoint are needed. Input constraints and calculation assumptions are in the [sources and limitations](../plugins/billfit/skills/billfit/references/sources-and-limitations.md). Use explicit offsets and duration units when correcting rejected input; do not weaken a guard to force a file through.

## Limits, further work and rollback

This is one part of the broader BillFit goal. Noisy/rotated OCR, duplicate bill documents, exact monetary rounding across all component combinations, a full reviewed tariff-candidate activation/rollback exercise and transport cancellation still require further work. Native Windows OCR, physical customer bills and independent human acceptance remain unverified. Good interval coverage does not establish seasonal representativeness, eligibility or actual savings.

No database migration, deployment or published release occurred. The code remains on an isolated draft branch. Rollback is restoring the previous committed application/Skill bundle and MCP launch profile, preserving user files and all observations. Do not roll back only one of the three shared modules. The tariff snapshots themselves are unchanged. Review and release approval are separate from passing source tests.
