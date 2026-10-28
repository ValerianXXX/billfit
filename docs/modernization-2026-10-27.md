# Verified rates, local bill input and MCP compatibility — 2026-10-27

Base `1cbf91ebc35ebff513b24beaab89fc8cc2476f6a`. The existing deterministic calculator, structured results and Green Button parser remain authoritative. Scope stays individually metered PG&E bundled residential electricity without solar/export, CCA or Direct Access.

## Current data verification

The [official rates page](https://www.pge.com/tariffs/en/rate-information/electric-rates.html) still lists March 1, 2026 to present. The downloaded [official workbook](https://www.pge.com/assets/rates/tariffs/res-inclu-tou-current.xlsx) is byte-identical to the packaged source hash `e071be6fd457a92da60637fc529c1e4c7a5620ffd83d3ae221819f7e4866995d`. All packaged [CPUC CARE/FERA income thresholds](https://www.cpuc.ca.gov/care/) match the June 1, 2026–May 31, 2027 rules. [Medical Baseline](https://www.pge.com/en/account/billing-and-assistance/financial-assistance/medical-baseline-program.html) remains based on medical need with practitioner certification.

August 18 verification was 70 days old. This established overdue verification, not a rate increase. Only `verified_on` metadata changes to October 27; no numerical rates, thresholds or effective windows change. Full source URLs, hashes, old/new metadata and deterministic comparisons are under `plugins/billfit/skills/billfit/data/verification/`. Dynamic HTML hashes are retrieval evidence, not tariff-change detectors.

Run the read-only check:

```sh
python plugins/billfit/skills/billfit/scripts/source_check.py
python plugins/billfit/skills/billfit/scripts/source_check.py --candidate path/to/reviewed-candidate.json
```

The checker never updates the calculator or its verification date. A changed workbook hash requires content/effective-date review. A candidate must pass complete structural, date, rule and numeric validation, then exposes winter/summer calculations for all five supported plans. It still returns `REVIEW_REQUIRED`; structural validity is not approval. Record source-to-cell/rule mapping, independently verify changed calculations, review the diff, and commit a separately dated version before activation. Never activate model-extracted tariff values directly.

Freshness now separates overdue verification, effective-window violations and unknown rate-change status. Stale snapshots withhold switching guidance. Expired assistance rules do not screen eligibility. Nonfinite/negative income and fractional/bool household size are rejected. Bill reconciliation retains stale-rate confirmation gates even when comparable components reconcile.

## Installation and client compatibility

A clean Windows environment exposed a pre-existing installation failure: `zoneinfo` lacked the IANA timezone database. Install the small platform-specific base requirement:

```sh
python -m pip install -r plugins/billfit/requirements.txt
python -m unittest discover -s plugins/billfit/tests -v
```

The existing standard-library stdio profile remains compatible with the protocol revisions it already implements (through 2025-06-18). For a current Hermes or other compatible MCP host, install the optional official SDK profile:

```sh
python -m pip install -r plugins/billfit/requirements-agent.txt
python plugins/billfit/skills/billfit/scripts/mcp_server.py --sdk
```

Use `.mcp.sdk.example.json` with absolute interpreter/script paths (Windows interpreter: `.venv\\Scripts\\python.exe`). SDK 2.3.0 owns discovery, envelopes, framing and initialization; tools reuse the same calculator and validate schemas. Current MCP 2026-07-28 and legacy 2025-11-25 were tested through real Windows subprocesses with the official SDK client, including discovery, assistance, rate calculation and malformed arguments. This establishes protocol/client-library compatibility, **not** a completed Hermes desktop/plugin installation.

An additional actual-host check used existing Hermes revision `afe53708ee7400919ae3e17a6dde9b02629e5c87` with its MCP client 1.26.0 in WSL. Its real MCP registry/dispatcher launched the Windows SDK server, discovered all seven BillFit tools and screened a synthetic two-person household with $40,000 gross annual income. CARE returned likely eligible with the verified $43,280 ceiling and non-stale rules; enrollment remained a human gate. No model calls, persistent configuration changes or real account access occurred. [Receipt](../plugins/billfit/skills/billfit/data/verification/hermes-mcp-host-2026-10-27.json). This covers actual host tool invocation, not a full model-driven bill-comparison conversation or permanent plugin installation.

Official protocol/SDK references verified October 27: [versioning](https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning), [Python SDK](https://github.com/modelcontextprotocol/python-sdk). No protocol string was relabelled on the old custom transport.

## Optional bill input

```sh
python -m pip install -r plugins/billfit/requirements-bill-input.txt
python plugins/billfit/skills/billfit/scripts/billfit_cli.py extract-bill --input-file request.json
```

`request.json`: `{"bill_file":"/absolute/path/to/bill.pdf"}`. The MCP equivalent is `billfit_extract_bill_fields`. PDF text stays local. For PNG/JPEG/TIFF, set `BILLFIT_TESSERACT_PATH` to an already installed trusted local OCR executable. A scanned PDF with no text remains unresolved; export a relevant page as an image for OCR. No cloud upload or new account access is added.

The extractor returns candidates for plan, comparable energy charge, Base Services Charge, baseline territory and total kWh with SHA-256, page, line, matched quote and image bounding box when available. Each field requires user confirmation. Conflicting values remain visible; whole amount due, account identity and eligibility are not inferred. Total kWh does not replace interval data. Confirm/correct candidate values before using existing `validate` or `compare` operations.

## Validation, limits and rollback

- Original configured environment: 20 baseline tests passed. Clean Windows initially failed on missing `tzdata`; the new requirement fixes that installation gap.
- Expanded suite: 28 tests passed with optional SDK/PDF dependencies. Winter/summer unchanged-rate checks retain identical five-plan components; existing exact-rate, holiday, baseline, discount and exclusion regressions still pass.
- Real synthetic PDF: four labelled fields extracted exactly, page/line evidence retained; missing baseline was reported. Conflicting-charge and total-due exclusion checks pass. No real customer bill was read.
- The initial host had no Tesseract, and missing-runtime behavior was tested. A follow-up unpacked official Ubuntu packages into an isolated WSL test directory without a system install. Actual Tesseract 5.5.0 extracted all five expected fields from one original clean synthetic PNG in 246 ms, retained bounding boxes within the image and excluded the unrelated amount due. Every field still requires confirmation. [Receipt](../plugins/billfit/skills/billfit/data/verification/2026-10-27-image-ocr.json) and [fixture](../plugins/billfit/tests/fixtures/synthetic-bill.png) are retained. This is not a noisy-photo accuracy estimate, native Windows OCR acceptance or a measured AI improvement.
- No plan change, application, deployment, rate activation or account action occurred. No database migration is needed. Roll back to the base commit and previous MCP launch profile; old snapshots remain in Git history. Any future numeric tariff version needs reviewed source mapping and regression evidence before release.

To repeat image acceptance, configure an existing trusted `BILLFIT_TESSERACT_PATH` and run `python scripts/evaluate-bill-image.py --output /absolute/new-image-result.json`. The script uses the committed original fixture and refuses to overwrite observations. A portable installation may also require its library path and `TESSDATA_PREFIX`; these are process-local runtime settings, not BillFit cloud configuration. See the [official Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html), checked October 27. The test runtime's Ubuntu package versions and hashes are retained separately; it is not distributed as a production dependency. No model or OCR cloud service was called.
