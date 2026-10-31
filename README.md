# BillFit

BillFit is a local-first Codex plugin and self-contained AI skill that compares supported PG&E residential electricity plans and screens common bill-assistance options.

## What it does

- Reads Green Button CSV or XML usage files locally.
- Compares E-1, E-TOU-C, E-TOU-D, EV2-A, and E-ELEC with versioned rate data.
- Screens CARE, FERA, and Medical Baseline pathways.
- Reconstructs comparable bill components to help validate a result.
- Keeps account login, plan changes, applications, and medical certification with the user.

Calculations are deterministic and use the official-source snapshots documented in [sources and limitations](plugins/billfit/skills/billfit/references/sources-and-limitations.md).

**Current development checkout, October 31:** usage validation preserves DST hours and rejects conflicting records or units; incomplete usage withholds switching savings. Optional bill extraction binds candidates to source hashes and page/line evidence. An opt-in image path now corrects a specified rotation and small skew locally, with evidence mapped back to original pixels. All values still require user confirmation. Installing `main` below does not install these draft changes.

The current full local suite passes **157 tests**. The optional SDK server keeps its event loop responsive during bill extraction, propagates cancellation to owned parsers and admits at most two extractions per server instance. Excess work returns `BILL_PARSER_BUSY` without queueing it. Actual SDK tests cover both transport profiles, cleanup, request isolation and continued use of the same connection. [Cancellation evidence and setup](docs/parser-cancellation-2026-10-30.md) explain the boundaries; the default synchronous legacy shim does not gain these capabilities.

The unchanged eight-image synthetic OCR matrix now passes **8/8 with optional preparation**, versus 6/8 without it. One quarter-turn is manually specified; all 38 returned values still need confirmation. Measured total parsing time rises from 2.15 to 5.91 seconds. Real local CLI/MCP calls pass, but these development samples do not establish customer-bill accuracy. [Image evidence, retained failures and rollback](docs/image-preparation-2026-10-31.md) show the scope. The [earlier input study](docs/bill-input-evidence-2026-10-30.md) remains unchanged.

Tariff values were last checked against official sources on **October 27, 2026**; this input change does not re-date or activate rate data. Earlier [source verification](docs/modernization-2026-10-27.md), [Hermes synthetic workflow](docs/hermes-workflow-2026-10-28.md), [interval repair](docs/interval-correctness-2026-10-29.md) and [CSV repair](docs/csv-energy-columns-2026-10-29.md) retain their original observations. Customer bills, native Windows OCR and independent user acceptance remain unverified.

Candidate tariff review now uses isolated snapshots, preventing an unapproved comparison from changing another calculation in the same process. A local maintenance tool prepares complete old/proposed snapshots and replays their calculations; it cannot approve or activate them. An October 31 source check found the official workbook byte-identical without resetting packaged verification dates. [Review package, evidence and remaining release work](docs/tariff-review-isolation-2026-10-31.md).

## Product discovery case

The evidence, rejected concepts, critical-data gap test, product decisions, and validation status behind BillFit are documented in [AI Skill Product Discovery](https://github.com/ValerianXXX/ai-skill-product-discovery/tree/main/cases/billfit).

## Requirements

- Hermes, Codex or another compatible MCP host; the CLI can also run directly
- Python 3.11 or later
- An individually metered PG&E residential bundled-electric account for personalized rate comparisons

BillFit's calculator uses the Python standard library plus `tzdata` on Windows. Run `python -m pip install -r plugins/billfit/requirements.txt` before the first use in a clean environment. The skill can run directly or through the bundled legacy MCP server. Current MCP discovery and PDF extraction are optional dependency profiles; they do not replace the calculator.

## Install from GitHub

Add this repository as a marketplace source:

```shell
codex plugin marketplace add ValerianXXX/billfit --ref main
```

Restart the ChatGPT desktop app, open the Plugins Directory, choose the **BillFit** source, and install **BillFit**.

## Example requests

- `Compare my PG&E plan using my Green Button file.`
- `Check whether my household may qualify for CARE or FERA.`
- `Tell me what BillFit still needs from me.`

A synthetic usage file is included at `plugins/billfit/skills/billfit/examples/demo_usage.csv`.

## Privacy and limits

BillFit reads supplied files locally. It does not need utility passwords, Social Security numbers, medical records, or income documents. It does not sign in to PG&E, change plans, submit applications, or make final eligibility decisions.

The AI host can send returned field values, evidence snippets, supplied household facts and calculation summaries to its configured model provider. Local parsing does not make a cloud conversation local. Review the host/model settings before supplying real data; the committed evaluation accepts only fixed synthetic inputs.

The MVP does not support solar or net export, CCA or Direct Access charges, master-metered service, gas, taxes, local surcharges, Climate Credits, or account-specific adjustments. Always confirm the current tariff before acting.

BillFit is an independent project and is not affiliated with or endorsed by PG&E or the California Public Utilities Commission.

See the [Privacy Policy](PRIVACY.md), [Terms of Use](TERMS.md), and [Support Guide](SUPPORT.md).

## NeedRadar portfolio relationship

BillFit is a bounded reference implementation in the [NeedRadar evidence-to-execution ecosystem](https://github.com/ValerianXXX/needradar/blob/main/docs/ECOSYSTEM.md). The relationship is descriptive only: BillFit has no NeedRadar runtime dependency, and it is not attached to a current opportunity card without a separate semantic-fit review.

Repository availability and passing tests remain engineering evidence, not adoption or demand validation. The machine-readable boundary is in [`needradar-project.json`](needradar-project.json).

## Test

From the repository root:

```shell
python -m pip install -r plugins/billfit/requirements-agent.txt -r plugins/billfit/requirements-image-input.txt
python -m unittest discover -s plugins/billfit/tests -v
```

To try the committed synthetic PDF from this checkout:

```shell
python -m pip install -r plugins/billfit/requirements-bill-input.txt
python plugins/billfit/skills/billfit/scripts/billfit_cli.py extract-bill --input-file plugins/billfit/skills/billfit/examples/synthetic-bill-extract.json
```

Images additionally require an existing trusted Tesseract executable through `BILLFIT_TESSERACT_PATH`; [.env.example](.env.example) documents it. The optional `requirements-image-input.txt` profile adds Pillow for explicit rotation/deskew; default extraction does not require it. Use the [synthetic request and preparation guide](docs/image-preparation-2026-10-31.md) for setup, original-coordinate evidence and recovery. No cloud fallback is configured.

To exercise the synthetic repeated-hour example from this checkout without credentials or a model:

```shell
python plugins/billfit/skills/billfit/scripts/billfit_cli.py compare --input-file plugins/billfit/skills/billfit/examples/synthetic-dst-compare.json
```

The two explicit offsets are distinct intervals. The intentionally sparse fixture is not sufficient for switching advice. No additional dependency or configuration is required for the interval changes.

## License

[MIT](LICENSE)
