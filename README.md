# BillFit

BillFit is a local-first Codex plugin and self-contained AI skill that compares supported PG&E residential electricity plans and screens common bill-assistance options.

## What it does

- Reads Green Button CSV or XML usage files locally.
- Compares E-1, E-TOU-C, E-TOU-D, EV2-A, and E-ELEC with versioned rate data.
- Screens CARE, FERA, and Medical Baseline pathways.
- Reconstructs comparable bill components to help validate a result.
- Keeps account login, plan changes, applications, and medical certification with the user.

Calculations are deterministic and use the official-source snapshots documented in [sources and limitations](plugins/billfit/skills/billfit/references/sources-and-limitations.md).

## Product discovery case

The evidence, rejected concepts, critical-data gap test, product decisions, and validation status behind BillFit are documented in [AI Skill Product Discovery](https://github.com/ValerianXXX/ai-skill-product-discovery/tree/main/cases/billfit).

## Requirements

- Codex or the ChatGPT desktop app with plugin support
- Python 3.11 or later
- An individually metered PG&E residential bundled-electric account for personalized rate comparisons

BillFit uses only the Python standard library. The packaged skill can run its deterministic calculator directly, while the full plugin also exposes the same engine through a bundled MCP server.

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

The MVP does not support solar or net export, CCA or Direct Access charges, master-metered service, gas, taxes, local surcharges, Climate Credits, or account-specific adjustments. Always confirm the current tariff before acting.

BillFit is an independent project and is not affiliated with or endorsed by PG&E or the California Public Utilities Commission.

See the [Privacy Policy](PRIVACY.md), [Terms of Use](TERMS.md), and [Support Guide](SUPPORT.md).

## Test

From the repository root:

```shell
python -m unittest discover -s plugins/billfit/tests -v
```

## License

[MIT](LICENSE)
