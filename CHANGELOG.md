# Changelog

## Unreleased — 2026-10-29

- Repair the `kwh` CSV header gap discovered by the shared-evidence study. Use one energy-column mapping for detection and reading, preserve explicit units and reject ambiguous energy/unit columns or conflicting kWh/Wh labels.
- Freeze 14 new input contracts before the repair: 3 passed, 7 failed and 4 errored initially; all 14 now pass unchanged. The complete existing optional-profile environment passes 86 tests. Actual CLI parsing/comparison of the original study input succeeds while withholding a recommendation for insufficient coverage.
- Add a synthetic CSV, request example, recovery instructions and before/after receipts. Historical research failures and tariff snapshots remain unchanged.

- Extract local CSV/XML/JSON validation into `billfit_usage.py` with shared domain errors; keep calculator/CLI entry points and transport profiles.
- Preserve absolute instants across daylight-saving transitions. Detect ambiguous/nonexistent local times, duplicate conflicts, overlaps and unsupported units instead of summing or silently dropping readings.
- Make duration units explicit, disclose inferred durations, bound file/interval/numeric ranges and conserve energy at actual tariff clock boundaries.
- Withhold switching savings for insufficient, inferred or coarse usage; retain a usage-review gate even when comparable bill components arithmetically reconcile. Reject non-finite, boolean and negative bill amounts.
- Keep all five-plan winter/summer component totals unchanged for the original regular-hour fixtures. Frozen boundary result: 1 pass/26 failures/1 error before, 28 passes after. Expanded full suite: 72 passed, including actual SDK subprocess error/recovery in both existing protocol modes.
- Add an explicit-offset synthetic example and dated official-page observations. No numeric tariff update, verification-date reset, new account scope, model call or production action.

## Unreleased — 2026-10-28

- Add a reproducible two-stage Hermes acceptance runner using fixed synthetic bill/usage files, real MCP tools, bounded file access and preserved failed observations.
- Clarify exact supplied file paths in the MCP parameter descriptions and skill after a model's first extraction argument was rejected. The unchanged task prompts and checks pass in a separate follow-up observation; no claims of broad quality or cost improvement.
- Preserve PDF fixture bytes and normalize text consistently across Windows/WSL Git. Add six offline evaluator tests, bringing the complete local suite to 34 passing tests.
- Document which returned facts a configured cloud model may receive. No account action, tariff activation, deployment or new account scope.

## Unreleased — 2026-10-27

- Reverify official rate workbook and assistance rules; retain unchanged numerical values with dated source hashes and review history.
- Separate stale verification from changed rates, withhold stale switching guidance, and reject expired assistance rules and invalid income inputs.
- Add non-activating candidate validation and winter/summer five-plan regression reports.
- Fix clean Windows installation with the IANA timezone requirement.
- Add optional SDK-backed modern MCP transport and local PDF/image bill candidates with user-confirmed evidence. Actual Hermes tool invocation and local WSL OCR on an original synthetic image pass; permanent host installation and real customer inputs remain unvalidated.

## 0.2.0 - 2026-08-18

- Prepared BillFit for public GitHub and OpenAI plugin submission.
- Made the skill bundle self-contained with a standard-library CLI fallback.
- Added public privacy, terms, support, security, logo, and review-test materials.

## 0.1.0 - 2026-08-18

- Added deterministic PG&E rate comparison, bill validation, and assistance screening.
- Added a bundled local MCP server and versioned official-source snapshots.
