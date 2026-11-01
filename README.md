# BillFit

BillFit is a local-first Codex plugin and self-contained AI skill that compares supported PG&E residential electricity plans and screens common bill-assistance options.

## What it does

- Reads Green Button CSV or XML usage files locally.
- Compares E-1, E-TOU-C, E-TOU-D, EV2-A, and E-ELEC with versioned rate data.
- Screens CARE, FERA, and Medical Baseline pathways.
- Reconstructs comparable bill components to help validate a result.
- Keeps account login, plan changes, applications, and medical certification with the user.

Calculations are deterministic and use the official-source snapshots documented in [sources and limitations](plugins/billfit/skills/billfit/references/sources-and-limitations.md).

## Development status and evidence

The current November 1 development branch contains draft improvements; installing
`main` below does not install them. Supported calculations remain deterministic,
local and subject to the returned review requirements.

| Area | Current behavior and evidence |
| --- | --- |
| Usage input | Preserves DST hours and rejects conflicting intervals, units and malformed numbers. [Numeric formats](docs/usage-number-format-2026-11-01.md) retain the 90-request comparison and recovery instructions. |
| Green Button meaning | Rejects incompatible export/cumulative quantities and ambiguous metadata; unresolved meaning or reading quality withholds switching savings and bill validation. [ESPI guide](docs/espi-semantics-2026-11-01.md) includes three runnable examples and the fixed 73-request comparison. |
| Bill PDF/image input | Returns unconfirmed fields tied to source hashes and page/line or pixel evidence. Optional local rotation/deskew retains original coordinates. [Input evidence](docs/bill-input-evidence-2026-10-30.md), [image preparation](docs/image-preparation-2026-10-31.md) and [native Windows observations](docs/native-windows-ocr-2026-11-01.md) preserve successes and failures. |
| MCP integration | Optional SDK mode supports cancellation, owned-child cleanup and two bounded concurrent extractions. [Setup and tests](docs/parser-cancellation-2026-10-30.md); the synchronous legacy shim has separate limits. |
| Bill reconciliation | Separates arithmetic agreement from sufficient period, usage and applicable-rate evidence. [Runnable example and boundaries](docs/bill-reconciliation-2026-10-31.md). |
| Rule maintenance | Builds isolated old/proposed snapshots with validation and explicit review before activation. [Rate review](docs/tariff-review-isolation-2026-10-31.md), [assistance review](docs/assistance-rule-review-2026-10-31.md), [fractional-income limits](docs/assistance-income-boundaries-2026-10-31.md) and [CARE name handling](docs/care-program-names-2026-11-01.md). |

The latest complete local optional-profile suite passes **229 tests, zero skips**.
For the frozen ESPI cases, correct rejection improves **0/38 → 38/38**, visible
review **0/20 → 20/20**, and valid controls remain **15/15**. Actual CLI and both
existing SDK modes pass, including error recovery on the same connection.
[Hashes, versions and original failed results](reports/espi-semantics-2026-11-01/verification.json)
make the scope reviewable. These are exposed synthetic cases, not customer-bill
accuracy, a new model-quality comparison or independent-user acceptance.

Packaged tariff verification remains **October 27, 2026**; input changes do not
activate rates or refresh that date. [Official-source verification](docs/modernization-2026-10-27.md),
[earlier Hermes synthetic workflow](docs/hermes-workflow-2026-10-28.md),
[interval repair](docs/interval-correctness-2026-10-29.md) and
[CSV repair](docs/csv-energy-columns-2026-10-29.md) retain their dated observations.
Exact utility rounding, residential Saturday holiday interpretation, real
customer bills, clean-machine setup and independent-user acceptance remain open.

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
