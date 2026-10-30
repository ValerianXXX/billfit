# CSV energy columns: October 29, 2026

The [shared-evidence study](https://github.com/ValerianXXX/ai-skill-product-discovery/pull/2) found a real parser gap: `start,duration minutes,kwh` was rejected with `CSV_HEADER_NOT_FOUND`. BillFit's header-discovery and row-read alias lists were separate and both omitted the plain `kwh` column. The study's failed Skill observations remain unchanged.

The parser now uses one energy-column mapping to discover and read the selected column. `kwh` and `usage (kWh)` carry an explicit energy unit; generic `usage`/`value`/`consumption`/`interval usage` retain the existing missing-unit warning when necessary. Two possible energy columns or two unit columns fail with a specific ambiguity error. An explicit kWh header conflicting with Wh row units fails rather than converting a potentially mislabeled value. Power units remain unsupported. The existing mixed-gas exclusion, duplicate handling, coverage and switching gates stay active.

## Frozen validation

Baseline code: `c8e9c305f048f66561a5312121bca22436417126`. Fourteen new tests and the synthetic fixture were frozen before implementation at `95396c51d9fb42fa94415dca46c331a33e2f550a`. Test source LF SHA-256: `2ad28ddb5ba5ef04d22fff467a1335520e0f59d5e107e01e8e85acc66b5b6a52`.

| Check | Before | After |
|---|---|---|
| Frozen header/unit/quality cases | 3 passed, 7 failures, 4 errors | 14 passed unchanged |
| Complete standard-library environment | Previous milestone had 72 tests | 86 run: 83 passed, 3 optional-integration skips |
| Complete existing optional-profile environment | Prior milestone passed 72 | 86 passed, zero skips |
| Original research CSV through actual CLI | Original study recorded CSV_HEADER_NOT_FOUND | Four unique intervals, 2.0 kWh, 240 elapsed minutes |
| Original research CSV through comparison CLI | Parsing previously blocked | Comparison returns with switching guidance withheld for insufficient usage |
| Conflicting unit / competing energy columns through CLI | Not safely distinguished | Exit code 2 with specific domain error |

The test fixture uses a separate synthetic date/order. An additional CLI check used the **exact original research CSV content**, whose LF hash and four command outcomes are retained in the [verification receipt](../plugins/billfit/skills/billfit/data/verification/csv-energy-verification-2026-10-29.json). It is a separately dated product repair check, not a replacement benchmark observation. Local logs include both the initial failures and the optional-profile run. The existing suite includes seasonal five-plan calculation regression and actual SDK error/recovery checks; tariff values and calculation rules were not changed.

## Try the synthetic example

From the repository root, using Python 3.11+ and the existing supported dependencies:

```sh
python plugins/billfit/skills/billfit/scripts/billfit_cli.py parse --input-file plugins/billfit/skills/billfit/examples/csv-energy-parse-request.json
python -m unittest discover -s plugins/billfit/tests -p test_csv_energy_columns.py
```

The example has five input rows including one identical repeat. Four hours do not establish monthly or annual savings. For a real ambiguous export, keep the original file, identify the correct meter/energy measurement and unit, and prepare a separate input containing one intended energy column. Do not simply rename a unit to suppress an error.

No model call, tariff activation, database migration, account change or production deployment is involved. A normal reviewed code revert restores the previous parser; it would again reject a plain `kwh` file. Preserve the new tests, observations and historical research when planning a rollback. Real customer file diversity, independent user acceptance, native Windows OCR and full bill reconciliation remain separate outstanding work.
