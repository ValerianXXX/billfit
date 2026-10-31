# Isolated tariff review and complete review snapshots

Observed October 31, 2026. Runtime `65d3c41779b604f89bc9dcc5a215d545d53995e7`,
based on image-input delivery `0a4cb36fd2f2aa8f030b884f34bfc11b612ef815`.
This stage repairs candidate validation and prepares review artifacts. It does
not install a tariff, approve a release or establish an operational rollback.

## Reproduced defects and changes

`compare_candidate` used to temporarily replace the module's `rate_data` function.
When candidate review and ordinary comparison were embedded in the same Python
process, an unapproved candidate could affect another request. A synchronized
thread test reproduced a one-kWh energy component changing from **$0.48 to $0.88**
while a synthetic candidate was under review. This is a reproduced code defect,
not evidence that a deployed customer bill was affected.

Each comparison now receives one detached rate snapshot and passes it explicitly
to eligibility, baseline allocation and plan calculation. Bill reconciliation
also uses one snapshot. Candidate review never changes the global lookup. Cached
bundled data is immutable text; callers receive independent dictionaries, so
editing a returned dictionary cannot poison later calculations. Mutation of a
candidate after review starts cannot change the calculated candidate version.

Candidate validation additionally rejects:

- changes to utility, service scope, schema, exclusions or eligibility lists that
  need an engine/rule review;
- percentage numbers such as `35` where the calculator expects a fraction such
  as `0.35`, and a nonzero discount for the `none` program;
- malformed workbook hashes, a different source-page identity and noncanonical
  dates; existing missing-key, numeric, effective-window and plan-rule checks remain.

These checks do not prove that a candidate matches the official source. They do
not approve any data, new account scope or assistance pathway. Source-to-cell
mapping and independent calculation review remain human release requirements.

## Review package and rollback boundary

The new local `tariff_review_bundle.py` command writes a fresh directory containing:

| File | Purpose |
| --- | --- |
| `baseline.json` | Complete current rates and assistance rules |
| `candidate.json` | Proposed rates paired with unchanged current assistance rules |
| `comparison.json` | Field differences and both seasonal five-plan calculations |
| `rollback-comparison.json` | Arithmetic replay of the preserved baseline |
| `manifest.json` | Content/runtime hashes, preparation time, unchanged source dates and remaining gates |

Existing destinations are not overwritten. The manifest is written last, so a
partial package fails verification. Verification checks bounded regular files,
hashes, exact runtime/bundled-rule identity, fixed gates and source dates, then
recalculates both comparisons. Rehashing an altered calculation is insufficient.
An edited approval, removed gate or fabricated source-verification date is rejected.
Hashes provide consistency checks, not a signature or proof of reviewer identity.

The package always returns `REVIEW_REQUIRED`, `approval: null` and
`automatic_activation: false`. It exposes no MCP tool, active-version pointer,
installer or publishing command. Its `synthetic_only` field is a declared test
classification, not independent source authentication. A caller cannot use a
manifest approval value to authorize publication.

The rollback exercise replays the complete old rate/assistance snapshot and
checks its numbers; **no running service is switched**. A reviewed operational
activation/rollback workflow is still outstanding. Assistance data is preserved
as part of the complete snapshot; this command does not prepare assistance-rule
changes. Seasonal scenarios are arithmetic regression inputs, not historical
bills proven to fall within the candidate's effective window.

## Verification

The unchanged baseline was the preceding 143-test local suite and its passing
delivery CI. No repeated baseline run was needed because product code was clean
and unchanged before the new branch.

- Seven isolation/rule methods frozen at `afb971f`: **16 failures and one error**
  initially, counting subtests. All seven pass after the repair.
- Four package contracts frozen at `42b8029`: four missing-module errors before
  implementation. Added manifest-tampering checks found two further failures;
  those are retained and repaired. Final targeted suite: **13 passed**, 0.689 s.
- A later actual subprocess CLI test covers preparation, verification and a
  redacted malformed-input failure. Full local optional-profile suite:
  **157 passed**, no skips, 74.011 s, Windows Python 3.11.3. Existing five-plan,
  interval/DST, freshness, OCR and real SDK checks remain in that suite.
- Separate actual CLI workflow creates and verifies a clearly synthetic package.
  A counterfactual E-TOU-D summer peak changes its 24-kWh scenario by $1.20; all
  other nine plan/season rows remain identical. Ordinary public calculation
  remains $0.48 before and after, and both packaged data files remain byte-identical.
  This does not assert a real tariff change or saving.
- Dependency consistency passes. No UI changed, model ran, real customer input
  was read, account action occurred or independent participant was observed.

[Machine-readable verification](../reports/tariff-review-verification-20261031.json),
[actual CLI receipt](../reports/tariff-review-workflow-20261031/receipt.json), and
[synthetic review manifest](../reports/tariff-review-workflow-20261031/review/manifest.json)
retain scope and reproduction details. Original failures are preserved as portable
text with hashes of the original local logs. Local paths are redacted.

## Current source observation

On October 31, the [official PG&E rates page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html)
still lists the March 1, 2026 residential workbook as current. A fresh download
of the [official workbook](https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx)
was 37,626 bytes, with unchanged SHA-256
`e071be6fd457a92da60637fc529c1e4c7a5620ffd83d3ae221819f7e4866995d`.
The [CPUC CARE/FERA page](https://www.cpuc.ca.gov/care/) still displays June 1,
2026–May 31, 2027 income tables. These observations do not establish a new rate
increase or a new assistance-rule activation.

The [read-only source receipt](../reports/tariff-review-source-observation-20261031.json)
also records retrieval of the assistance and Medical Baseline pages. Retrieval
of changing HTML alone is not complete content/rule verification. Packaged values,
effective dates and `verified_on: 2026-10-27` remain unchanged. No metadata was
re-dated merely because the source-check command ran.

## Run and review

Use the existing interpreter/base requirements; no dependency or configuration
change is required. These commands are separate maintenance tools, not model tools.

```shell
python plugins/billfit/skills/billfit/scripts/source_check.py --candidate path/to/candidate.json
python plugins/billfit/skills/billfit/scripts/tariff_review_bundle.py prepare --candidate path/to/candidate.json --output-dir path/to/new-review
python plugins/billfit/skills/billfit/scripts/tariff_review_bundle.py verify path/to/new-review
python scripts/verify-tariff-review-workflow.py --output-root path/to/new-synthetic-observation
```

The last command only uses packaged public rules and a labelled counterfactual;
it cannot accept a real bill or arbitrary tariff path. `prepare --synthetic`
explicitly labels other synthetic exercises. Invalid/changed packages return
`TARIFF_REVIEW_FAILED` through the CLI without echoing input content. Preserve
partial evidence and use a new directory after repairing the cause. A changed
runtime or bundled baseline requires a fresh review; do not alter hashes to
pretend the old review applies.

Before any actual data update, review the official content, source mapping,
effective window and independent calculations, then provide the exact proposed
version, complete old snapshot and operational release/rollback procedure for
owner approval. This task has not supplied or fabricated that approval.

No migration is needed for this source change. A normal reviewed revert restores
the previous code but also its shared-state defect; preserve historical packages
and observations. Remaining BF-02/BF-03 work includes actual reviewed activation,
operational rollback, assistance-update preparation and broader cent-rounding /
billing-period reconciliation. Independent human/customer acceptance remains open.
