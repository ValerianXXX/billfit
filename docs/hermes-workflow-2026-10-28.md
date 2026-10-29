# Model-selected BillFit workflow: frozen protocol, October 28, 2026

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

No earlier model-driven BillFit observation exists for a controlled before/after comparison. This is one two-stage acceptance scenario, not a model leaderboard, noisy-bill accuracy estimate, real household savings result or permanent plugin installation test. Native Windows OCR and real customer inputs remain unverified. There is no deployment, migration or runtime behavior change; remove the evaluator and use the earlier launch profile to roll back this addition. The existing rate snapshot and human gates are unchanged.

Official [PG&E rate page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html) and [CPUC CARE/FERA page](https://www.cpuc.ca.gov/care/) were re-opened October 28 (America/New_York): their displayed effective windows and the two-person CARE threshold match the existing snapshot. This page check does not re-download/reverify the workbook bytes or reset the packaged October 27 verification date.

Live results are appended only after actual execution; no new model observation is claimed by this protocol commit.
