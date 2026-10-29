# Model-selected BillFit workflow: protocol and observations, October 28, 2026

The earlier [Hermes receipt](../plugins/billfit/skills/billfit/data/verification/hermes-mcp-host-2026-10-27.json) verified host discovery and direct dispatch with zero model calls. This protocol adds an opt-in real model-selected workflow. It does not replace the deterministic calculator or imply a completed utility account action.

## Fixed tasks and evidence

Two independently initialized model stages use the same installed Hermes model/provider and the repository's BillFit skill. The first reads an original synthetic PDF, retains all five unconfirmed fields with exact page/line/quote/hash evidence, screens a declared two-person/$40,000 household and leaves missing interval usage, field confirmation and application actions open. No usage file is available to the model in that stage.

The second stage contains an explicit **synthetic test fixture declaration of confirmation**, not a real user's approval. It supplies the already committed one-day `demo_usage.csv` and asks for parsing, E-TOU-D/E-TOU-C comparison and bill reconciliation. It deliberately pairs a $12.34 energy component with an unrelated one-day usage fixture. The deterministic result is a mismatch: calculated energy $4.90, difference -$7.44; one-day comparable totals are $5.69 and $5.81 respectively. One day is limited coverage. The model must report the mismatch and withhold switching action. Likely CARE eligibility cannot be treated as current enrollment.

The original PDF is a fixture, not a report or a utility statement. It was rendered and visually inspected; its five labelled values are legible and the unrelated $98.76 amount due is excluded. PDF SHA-256: `baa1c513a0914f41d0580e4b2c86ee5c1eff182e5f4a3b36eba8925fade1a9d0`. CSV SHA-256 after LF normalization: `8de63202ed5a06dc8de76117dab7401eefc3b6ca1f02808bdb3992cf1187fc8e`. Both are enforced before running. The source commit and runner hash bind each observation to its protocol.

No model/provider defaults change. The evaluator creates a temporary Hermes home, exposes exactly seven real BillFit MCP tools and limits each stage to four native agent iterations and eight dispatched tool calls. A small evaluator boundary maps only the two fixture basenames to local files and rejects generated interval arrays, unavailable files and undeclared household facts. It does not mock results or repair model arguments. Provider internal retries may differ from agent iterations; available session counters are recorded separately. Receipts never substitute a zero for unknown billing.

## Running

Install only the existing optional SDK/PDF profiles if needed; an already authorized Hermes environment is required. No package is installed by the evaluator.

Prepare a local JSON configuration with the trusted server interpreter, absolute repository script path and an empty environment:

```json
{"command":"/absolute/server/python","args":["/absolute/billfit/plugins/billfit/skills/billfit/scripts/mcp_server.py","--sdk"],"env":{}}
```

Run using the existing Hermes Python, not a new agent installation:

```sh
HERMES_PYTHON scripts/probe_hermes_workflow.py --hermes-root /path/to/hermes-agent --output /outside/repository/preflight.json < server-config.json
HERMES_PYTHON scripts/probe_hermes_workflow.py --hermes-root /path/to/hermes-agent --execute-model --output /outside/repository/new-observation.json < server-config.json
```

The default preflight discovers tools without model calls. A live run requires a clean committed tree and refuses to overwrite an observation. Keep machine-specific configuration outside tracked files. WSL clients can launch a Windows interpreter using its `/mnt/.../python.exe` path and pass the Windows absolute server script path. The evaluator checks that the script resolves to this checkout.

Repository attributes normalize text for both Windows and WSL Git and preserve PDF/PNG fixture bytes as binary. The initial live invocation stopped before model initialization because WSL interpreted the Windows checkout's CRLF text as uncommitted changes. That precondition failure is retained separately; no model call occurred in it.

Original file bytes are parsed locally. The configured model receives the prompt and returned synthetic field values, evidence snippets, income facts, summaries and calculation outputs. Using BillFit with a cloud host can send analogous returned facts to that host's model provider; local file parsing alone does not make the entire model conversation local. This acceptance script accepts only the fixed synthetic inputs.

## Assessment and limits

The checks separately cover selected tools, file boundaries, exact extracted values, unconfirmed source retention, screening status, pending human actions, usage quality, calculated amounts, source dates, mismatch handling and absence of claimed account actions. An empty answer, failed tool, fabricated source or changed success label cannot pass. Six offline tests exercise evaluator failure cases without model access.

The October 27 host check has no model baseline. The two observations below use the same model, task prompts, fixtures, evaluator and pass criteria, with exact-path guidance added to the actual skill/tool descriptions between them. Each has only one run; sampling, service latency and cache effects are uncontrolled. They do not establish a general quality, latency or cost improvement. This remains one two-stage acceptance scenario, not a model leaderboard, noisy-bill accuracy estimate, real household savings result or permanent plugin installation test. Native Windows OCR and real customer inputs remain unverified. No deployment or migration is needed; revert the evaluator and path-description commits to restore the previous skill/launch profile. The existing calculator, rate snapshot and human gates are unchanged.

Official [PG&E rate page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html) and [CPUC CARE/FERA page](https://www.cpuc.ca.gov/care/) were re-opened October 28 (America/New_York): their displayed effective windows and the two-person CARE threshold match the existing snapshot. This page check does not re-download/reverify the workbook bytes or reset the packaged October 27 verification date.

## Initial actual observation

At `7392a56814e35065ad9e5ad2b44c7238afd5c845`, existing Hermes `afe53708ee7400919ae3e17a6dde9b02629e5c87` / `gpt-5.6-sol` / `openai-codex` completed the two stages in 70,490 ms, with six reported model API calls and 40,690 tokens. Stage 1 failed the file boundary check: its first extraction call did not use the supplied exact filename, and was rejected before any file read. The evaluator did not retain that rejected argument, so its exact value and the reason for the model's choice are unknown. The model subsequently corrected the filename. All final fields and sources, confirmation gates and assistance results were correct. Stage 2 passed all checks, including deterministic totals, limited coverage and the deliberate mismatch. **Overall result: FAILED_CHECKS**, retained unchanged in `hermes-workflow-attempt-1.json`.

The next revision clarifies exact supplied paths in the actual MCP parameter descriptions and skill. The task prompts, model selection, fixtures and pass criteria stay unchanged. It does not weaken the file guard or reclassify the first observation. Reported cost status was `included`, estimated cost zero with source `none`; actual billing is unknown.

## Follow-up actual observation

At `90ffa2bf2bc54d990c05572f462b4be2bcec9c49`, both stages passed all 23 fixed checks. The raw [second observation](../plugins/billfit/skills/billfit/data/verification/hermes-workflow-attempt-2.json) and [first observation](../plugins/billfit/skills/billfit/data/verification/hermes-workflow-attempt-1.json) are unchanged execution outputs. The earlier [CRLF precondition failure](../plugins/billfit/skills/billfit/data/verification/hermes-workflow-precondition-failure.json) occurred before any model initialization.

| Measure | First observation | After path guidance |
| --- | --- | --- |
| Fixed stage results | Stage 1 failed file boundary; stage 2 passed | Both stages passed |
| Rejected file calls | 1, followed by recovery | 0 |
| Successful real MCP calls | 6 | 6 |
| Reported model API calls | 6 | 5 |
| Reported tokens | 40,690 | 34,489 |
| Whole runner elapsed | 70,490 ms | 45,782 ms |
| Actual billed dollars | Unknown | Unknown |

In the passing run, stage 1 took 24,690 ms with two model calls and 14,570 tokens; stage 2 took 17,538 ms with three model calls and 19,919 tokens. Total runner time includes setup/shutdown. The original PDF bytes were processed by local pypdf; five candidate values and exact evidence reached the configured model. Every field remained unconfirmed in stage 1. In stage 2 the model used 24 actual synthetic intervals, retained the one-day coverage warning and source dates, reported the $7.44 energy mismatch and withheld switching. No utility action tool exists in the exposed surface and none was claimed. Temporary state was removed in both runs.

Environment: existing WSL Hermes Python 3.11.15/client MCP 1.26.0 to the existing Windows Python 3.11.3/server MCP 2.3.0/pypdf 6.21.3 profile. Public version metadata was checked around execution; no new model service, dependency installation or permanent host configuration was added. The runner hash is identical between actual observations: `70c018bce32e463369303e113b0d1e250f548ce044804ced3a1158a630e7887c`. All 34 local tests passed before model execution; eight affected PDF/MCP/freshness checks passed again after the tool-description change. CI remains the independent milestone check.
