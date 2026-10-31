# Assistance-rule candidate review

Observed October 31, 2026. Runtime `a4a377446cc92f4ba5feddfaf5c8aa0e7cfb39b2`,
based on reconciliation delivery `efd6ec3fd560da85c48021578c7f62824a2765cd`.

The previous maintenance command preserved assistance data but could only review
new rates. It now prepares income-table updates using the existing deterministic
screening engine. Ordinary CLI/MCP screening continues to read packaged rules;
it cannot accept a candidate snapshot or pretend that a future date is current.
This closes assistance-update **preparation**, not publication or enrollment.

## Scope and implementation

The accepted candidate is a complete copy of the existing assistance schema.
Income thresholds must be positive bounded whole dollars, household 1 and 2 must
agree, limits must not decrease with household size, and FERA must remain above
CARE including the additional-person progression. Dates must be canonical,
within the supported 1900–9998 review range, ordered, and not claim a future
verification date. These checks do not authenticate a claimed verification date.

Program lists, aliases, notes, source identity, status and schema stay unchanged.
Changes to eligibility pathways or source mapping need a separate rule/engine
review. This is deliberately a threshold/date update interface, not a mechanism
for a model to rewrite policy. The maintained data files are byte-identical.

An internal snapshot seam detaches the selected rules before screening. Review
never patches a global lookup. The fixed concurrency test pauses a proposed
review, edits its caller-owned input and runs ordinary screening concurrently;
the proposed snapshot stays fixed and the ordinary CARE limit remains $43,280.
This is in-process isolation, not a multi-process installation transaction.

## Review artifacts and reproducibility

Assistance candidates produce schema version 2 of the existing review package:

| Artifact | What it preserves |
| --- | --- |
| `baseline.json`, `candidate.json` | Complete rates and assistance snapshots |
| `comparison.json`, `rollback-comparison.json` | Existing five-plan/season arithmetic |
| `assistance-comparison.json` | Old/new screening at explicitly recorded dates |
| `rollback-assistance-comparison.json` | Baseline assistance replay |
| `manifest.json` | Runtime/content hashes, both source dates and remaining gates |

The synthetic workflow changes 18 threshold fields by $100 and produces 168
screening scenarios: household sizes 1–9 and 12; below/at/above old and proposed
limits; missing income; each currently supported categorical program and alias;
medical need; effective-window edges; and the 45/46-day freshness boundary.
Scenario count is coverage, not measured eligibility accuracy or customer impact.

Dates are embedded in each scenario, so replay does not silently switch to the
day verification is run. Future/disjoint effective windows visibly return
`rules_outside_effective_window` where appropriate. The matrix uses whole-dollar
income and does not establish how a utility rounds fractional annual income.
Existing fractional-income behavior remains a separate rule-interpretation gap.

The verifier recomputes both comparisons and baseline replays, checks fixed
release gates and source dates, and rejects rehashed fake screening results.
Both `approval: null` and `automatic_activation: false` remain mandatory.
Hashes establish consistency, not authorship or source authenticity.

Rate-only callers retain version-1 structure. A different runtime invalidates
earlier runtime-bound packages, including historical committed examples; preserve
those observations and prepare a fresh review instead of editing their hashes.
Verification does not install a pointer, publish data or switch a running service.

## Verification and evidence

The unchanged predecessor passed 178 tests and
[hosted CI 41208411501](https://github.com/ValerianXXX/billfit/actions/runs/41208411501).
That baseline was reused rather than repeated before implementation.

- Ten methods frozen at `7587ee3` initially produced one pass, one failure and
  eight missing-interface errors. All ten passed unchanged in 2.389 seconds.
- Two later contracts cover combined rate/assistance updates and absent inputs.
  Full Windows Python 3.11.3 optional-profile suite: **190 passed, no skips,
  56.265 seconds**. Existing interval/DST, reconciliation, image parsing and
  actual local SDK transport/recovery tests remain included.
- Five actual local CLI invocations exercise ordinary screening before/after,
  preparation, replay and rejected overwrite. Seven workflow checks pass; the
  proposed CARE outcome differs at the synthetic boundary while ordinary output
  and all packaged data remain unchanged. Original responses are retained.
- No UI or dependency changes, model calls, real customer bills, account actions,
  new Hermes-client observation, independent participants or production changes.

[Verification receipt](../reports/assistance-review-verification-20261031.json),
[actual CLI receipt](../reports/assistance-review-workflow-20261031/receipt.json),
[synthetic manifest](../reports/assistance-review-workflow-20261031/review/manifest.json)
and [source observation](../reports/assistance-source-observation-20261031.json)
preserve the evidence. Portable failure/success logs are linked from the receipt.
Inherited `official-current` metadata in a synthetic candidate is not an assertion
that the counterfactual numbers are official; use only its labelled test context.

## Official source observation

The [CPUC CARE/FERA page](https://www.cpuc.ca.gov/care/) reviewed on October 31
still gives income tables effective June 1, 2026 through May 31, 2027. Its CARE
and FERA thresholds agree with the packaged tables. A fresh bounded download
records the HTML hash separately; number-presence checks alone do not establish
source-to-field mapping. No new threshold change is asserted, and packaged
`verified_on: 2026-10-27` is retained. Existing categorical paths are covered by
regression, not a newly completed audit of every official program.

## Run

Use the existing Python requirements and the current draft checkout:

```shell
python scripts/verify-assistance-review-workflow.py --output-root path/to/new-synthetic-observation
python plugins/billfit/skills/billfit/scripts/tariff_review_bundle.py prepare --assistance-candidate path/to/rules.json --output-dir path/to/new-review
python plugins/billfit/skills/billfit/scripts/tariff_review_bundle.py verify path/to/new-review
```

Add `--candidate path/to/rates.json` to review both rule sets together. At least
one candidate is required. Add `--synthetic` to label other counterfactual
exercises. The included workflow only generates fixed synthetic requests and
cannot accept a bill, account credential or arbitrary policy file. Invalid CLI
input is redacted as `TARIFF_REVIEW_FAILED`; existing directories are preserved.

No environment variable, service, dependency or database migration is added.
An ordinary reviewed source revert removes this preparation interface; preserve
all historical receipts. No production rollback was exercised. Actual publication
still needs independent source mapping, the exact proposed version, a complete
backup, tested installation/operational rollback and owner approval. Real bills,
fractional-income rule interpretation and independent user acceptance remain open.
