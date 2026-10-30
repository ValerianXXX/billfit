# Bill input evidence and parser isolation

Observed October 30, 2026. This is an unmerged development milestone, stacked on
the CSV input repair. It does not change tariffs, utility rules or account scope.

## Problem and result

The original adapter removed commas before validating money, accepted the
supported prefix of a longer plan name and treated a credited amount as a
positive charge. Its image subprocess read a mutable original file, while the
evidence hash was calculated later. TSV geometry/confidence were not validated.
Process output was captured without a byte cap until the child had finished.

Candidate extraction now validates the complete value, and unsupported or
ambiguous text stays in `unresolved_fields` with source evidence. Repeated and
conflicting values retain their own locations; none are added, selected,
confirmed or passed to the calculator automatically.

The implementation separates four responsibilities:

| Module | Responsibility |
| --- | --- |
| `bill_input.py` | Snapshot/hash binding, field syntax, review candidates and source-change rejection |
| `bill_ocr.py` | Exact TSV schema, page/word geometry and identity, word confidence and line evidence |
| `bill_pdf_worker.py` | Optional pypdf parsing in a one-shot child with fixed error codes |
| `bill_process.py` | Shared deadline, bounded stdout/stderr capture and cleanup of the owned child |

OCR source boxes include the words contributing to a candidate, in original
image pixels. A minimum word confidence below 70 adds a review flag; -1 remains
unknown. This threshold is a heuristic, not calibrated accuracy. Even a high
score cannot confirm a field. PDF text retains page, line, quote and offsets;
it does not invent pixel coordinates.

One additional actual CLI test exposed pypdf printing the first bytes of a bad
PDF on stderr. The original failed run is retained by hash in the verification
receipt. PDF parsing now uses an isolated child and the same bounded capture;
its diagnostics are discarded while structured, fixed errors remain visible.
No global logger or stderr configuration is changed in the MCP host.

## Fixed before/after evidence

The 15 original test methods were frozen before implementation at
`a3864e8d8c4078d374384920507b2eac4c966f88`. A subsequent test-harness-only
correction at `e6fece736db8981e79af1110d4d9a12d5c992164` prevents failed
subtests from causing secondary exception-access errors. Inputs and expected
behavior were unchanged. The corrected baseline has 24 failed assertions/subtests
and two errors across those 15 methods; three methods passed. The same frozen
methods now all pass.

Nine original synthetic fixtures and the evaluator were frozen at
`beec256` before the product edit. All eight images were visually inspected.
They are deliberately labeled synthetic, contain no account/customer data and
are not PG&E bill templates or an independent holdout set.

| Actual local parser case | Before | After |
| --- | --- | --- |
| Clean image | Pass | Pass |
| Low-contrast image with deterministic noise | Pass | Pass |
| Six-degree skew | Missing Base Services Charge | Still missing; ambiguous source excerpt and low-confidence flag exposed |
| Ninety-degree rotation | Five fields missing | Still five fields missing; explicit no-fields recovery guidance |
| Malformed comma grouping | Wrong amount accepted | Rejected with a sourced unresolved field |
| Credit suffix | Positive charge accepted | Rejected with a sourced unresolved field |
| Unsupported plan suffix | Supported prefix accepted | Rejected with a sourced unresolved field |
| Two conflicting energy charges | Pass | Pass; both values retained |
| Two identical PDF pages | Pass | Pass; ten candidates across two pages, no addition |

Image matrix: **3/8 to 6/8**, retaining two failed cases. Both versions use the
same Tesseract 5.5.0 / Leptonica 1.86.0 binary, fixed English PSM 6, Python
3.14.4 in the existing WSL runtime and identical input hashes. The skewed OCR
reads the amount as `$0 719`; the adapter does not guess that it means $0.79.
Valid-field recall remains 32/38 in both observations. Unexpected values fall
from three to zero, rather than recovering the six missing values. This demonstrates safer
handling of these examples, not general OCR or real-bill accuracy.

The eight calls took 1,900.473 ms before and 1,950.022 ms after in these single
observations. They do not establish a latency improvement. The repeated PDF uses
Windows Python 3.11.3 with pypdf 6.21.3. Authoring used bundled ReportLab/Poppler
and a separate pypdf version; those are not added as product dependencies.
No cloud/model call occurred. Dollar cost is unknown, not zero.

The full existing Windows environment passes **117 tests in 15.018 seconds**,
with no skips. In addition to the frozen contracts, these include real owned
process timeout/overflow/reaping, concurrent pipe reading, actual malformed and
repeated PDFs, changed originals, encrypted/page-limit rejection and real MCP
SDK 2.3.0 subprocess error/recovery in protocol modes 2026-07-28 and legacy
2025-11-25. This is client-interface validation; no new Hermes/model-selected
workflow or independent human acceptance was run. Earlier observations remain
dated to their original code.

The [verification receipt](../reports/bill-input-verification-20261030.json) binds
all four source modules, frozen tests, evaluator, original logs and both matrix
observations. The unchanged matrix evaluator records its original two-module
hash scope; the verification receipt adds the process/PDF-worker hashes.

## Run and configure

From the repository root, using the Python environment that runs BillFit:

```shell
python -m pip install -r plugins/billfit/requirements-bill-input.txt
python plugins/billfit/skills/billfit/scripts/billfit_cli.py extract-bill --input-file plugins/billfit/skills/billfit/examples/synthetic-bill-extract.json
python -m unittest discover -s plugins/billfit/tests -v
python scripts/evaluate-bill-input-matrix.py --kind pdf --output reports/my-pdf-observation.json
```

The last command refuses to overwrite an observation. For images, configure an
already installed trusted Tesseract executable in the host environment:

```powershell
$env:BILLFIT_TESSERACT_PATH = 'C:/path/to/trusted/tesseract.exe'
python scripts/evaluate-bill-input-matrix.py --kind image --output reports/my-image-observation.json
```

That Windows path is an operator configuration example, not a validated native
Windows installation. On Linux/WSL set the equivalent environment variable and
any library/tessdata paths required by the existing installation. BillFit does
not install Tesseract or load `.env` automatically. The matrix runner accepts
only committed synthetic fixtures; the regular tool accepts the exact
user/client-supplied local path. No account credentials or cloud fallback exist.

The optional SDK profile remains documented in the earlier modernization guide;
tool names and request parameters are unchanged. New response evidence/quality
fields are additive. A host may send returned values and excerpts to its model
provider; local parsing does not make a cloud conversation private.

## Limits, recovery and remaining work

Files are capped at 25 MB, page evidence at 25 pages, extracted text at one million
characters and OCR TSV at 50,000 rows. Each child has a 30-second deadline,
with bounded cleanup time; combined stdout/stderr is capped at 2 MB for OCR or
8 MB for PDF. Only stdout is retained. Errors are fixed domain codes, including
`BILL_SOURCE_CHANGED`, `OCR_OUTPUT_INVALID`, parser timeout/output errors,
`PDF_LIMIT` and `PDF_TEXT_FAILED`. Supplied originals are never rewritten.
Temporary snapshots are removed after success or handled failure.

These are file/time/output bounds, **not a hard RAM cap, global concurrent-job
limit or OS sandbox**. Native image decoding and PDF decompression can consume
memory before the text limit applies. A forcibly terminated host may leave a
temporary snapshot under its OS temp directory. Trusted executables and the
existing file-permission/privacy requirements still apply.

For unreadable, rotated or skewed input, retain the original and request an
upright/readable copy or verified fields. Future preprocessing needs explicit
coordinate mapping and a new frozen comparison; silently substituting OCR digits
or selecting whichever retry returns more fields is not acceptable. Noisy
photographs, varied real bill layouts, native Windows OCR, user cancellation,
hard memory limits and independent user acceptance remain open. No multi-account,
credit, export or new-region calculation scope is added.

These are the boundaries of the original input milestone. The subsequent
[SDK parser cancellation milestone](parser-cancellation-2026-10-30.md) validates
cooperative cancellation and two-parser admission in both SDK transport profiles.
The default synchronous shim, hard memory limit and independent user acceptance
remain outside that follow-up's verified scope.

Official documentation checked on October 30:

- [Tesseract command-line and TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html):
  retain the existing local command and validate its documented page/word fields.
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html):
  text extraction is not OCR; whole-page content can consume substantial memory.
  This informed the explicit limits rather than a claim of hard memory isolation.

No external product source was copied or new parser dependency introduced.

## Review and rollback

Review the frozen contracts, source commit `c5c9963`, actual failure receipts
and current draft as a separate layer over the CSV repair. There is no database
migration, tariff activation, release or deployment. Revert the source commit
through a normal reviewed commit to restore the previous adapter, retaining the
original files and observations. Older code restores the known ambiguity and
diagnostic risks; it is not an equivalent validated fallback. Main remains
unchanged until separately approved.
