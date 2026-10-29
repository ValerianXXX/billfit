# Changelog

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
