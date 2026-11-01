# CARE program names and unresolved enrollment inputs

Observed November 1, 2026. This is a draft source change, based on `2815926`.
The frozen protocol is `5942f3663b847b70d0bb3b7dc0ff00cebd47a87b`; the tested
runtime is `d485c526f996e41cd07511c878ac13d2c12c5b5a`.

## Problem and source interpretation

Full official names such as the expanded WIC label previously failed the short
alias lookup. A supplied categorical pathway could disappear, leaving only an
income-based negative. Invalid program entries could also escape the CLI as
an unstructured exception instead of a usable correction request.

The [PG&E eligibility list](https://www.pge.com/en/account/billing-and-assistance/financial-assistance/care-eligibility.html)
and [CPUC program list](https://www.cpuc.ca.gov/care/) were inspected on November 1.
The new resolver covers qualified expanded names for already supported pathways.
Healthy Families A & B retains the existing `medicaid_medi_cal` identifier because
PG&E identifies it as Medi-Cal for Families. This does not infer someone's age,
medical condition or current enrollment.

CPUC specifies a free-lunch qualifier for NSLP; the PG&E bullet omits it. Bare
NSLP is therefore unresolved rather than automatically broadened or denied.
Ordinary Head Start does not establish income-eligible Tribal participation;
Medicare is not silently mapped to Medicaid; a combined CalWORKs-or-Tribal label
does not identify which enrollment was supplied. These are input safeguards,
not claims that the utility denies anyone with those descriptions.

## Behavior and compatibility

`assistance_programs.py` owns input validation, exact name normalization and
match provenance. It normalizes case, punctuation, whitespace and Unicode
compatibility forms. It performs no substring/fuzzy matching, inference or model
call. Existing canonical IDs and configured aliases remain supported. Names
added by this reviewed code cannot enable a pathway absent from the selected
snapshot's supported program list.

The additive `categorical_program_review` result includes a separate mapping
date, source URLs, each matched input/index/canonical ID and each unrecognized
input/index. Duplicate names retain their input evidence but do not duplicate
the CARE pathway. `needs_confirmation` adds `ASSISTANCE_PROGRAM_CONFIRMATION`.
An unknown name is not proof of ineligibility; independently supported income
or known-program results remain available. Hosts must show both that result and
the unresolved input instead of collapsing the entire screen to approval/denial.

At most 32 names of 160 characters each are accepted. Wrong containers, invalid
members and blank/oversized values return `INVALID_PUBLIC_PROGRAMS` without
echoing the input in the error. The SDK may reject schema violations earlier as
`INVALID_ARGUMENTS`; the same connection remains usable. Callers should correct
inputs, not truncate program names. No enrollment documents are requested.

The income and rate JSON files, their effective windows and October 27 verification
dates are byte-identical to the base. A November 1 mapping check does not refresh
the underlying financial rules or bypass stale/expired gates. The maintenance
package fingerprint now includes this resolver. Old runtime-bound packages remain
historical; prepare fresh packages rather than changing their hashes. The existing
candidate interface still rejects program/alias edits and cannot activate rules.

## Frozen comparison and verification

All households are synthetic. The high income intentionally isolates the
user-reported categorical path; it is not an observed household or proof of
compatible real-world income and enrollment. The same evaluator, fixture and
37 actual CLI requests ran against the unchanged base and the new runtime.

| Fixed category | Before | After | Interpretation |
| --- | --- | --- | --- |
| Qualified official labels recognized correctly | 4/15 | 15/15 | Eleven missed name mappings repaired |
| Unresolved labels with explicit review | 0/10 | 10/10 | Previously hidden review is now visible |
| Invalid inputs with a structured domain error | 0/6 | 6/6 | Error/recovery behavior repaired |
| Income decision controls retained | 6/6 | 6/6 | Existing six boundaries unchanged |

Neither version automatically qualifies the ten negative/unresolved controls.
The extra review prompts are necessary work, not a measured reduction in user
effort. These exposed, source-authored cases are not a held-out accuracy estimate.

Fourteen pre-implementation test methods initially produced 20 failed assertions
and 23 errors/subtest errors; one method passed. They pass unchanged after the
repair in 4.570 seconds. Some original failures concern missing review metadata,
not factual mistakes. The full Windows Python 3.11.3 optional-profile suite passes
**214 tests, zero skips, 51.937 seconds**. Existing pricing, source snapshots,
fractional-income/stale rules, image/PDF parsing, cancellation and SDK recovery
remain covered. Actual MCP SDK 2.3.0 tests pass both existing `2026-07-28` and
`legacy` profiles; this is not a new Hermes/model-selected or utility workflow.

The [receipt](../reports/care-program-names-2026-11-01/verification.json) retains
the failing contracts, original CLI outputs, source observations and hashes.
Zero new model calls or enrollment actions occur. Total cost, customer benefit,
independent-human acceptance and population accuracy are unmeasured.

An additional Windows `python -S .../billfit_cli.py scope` diagnostic fails on
both the unchanged base and this runtime because disabling site packages also
removes the documented required `tzdata` package. Both failures are retained.
The successful CLI/full-suite observations use the installed requirements; they
are not evidence of dependency-free Windows operation. No timezone workaround,
global setting or product dependency was changed to obtain a passing result.

## Run and rollback

Use the existing checkout/environment; no new dependency, setting, service or
database migration is required. The committed example is deliberately synthetic:

```shell
python plugins/billfit/skills/billfit/scripts/billfit_cli.py assistance --input-file plugins/billfit/skills/billfit/examples/synthetic-care-program-review.json
python -m unittest discover -s plugins/billfit/tests -p test_care_program_names.py -v
python scripts/verify-care-program-names.py --checkout . --output path/to/new-observation.json
```

The example recognizes WIC while retaining NSLP for confirmation. To reproduce
the earlier observation, run the same frozen evaluator with `--checkout` pointing
to the base commit. Existing observation files cannot be overwritten. The full
suite uses the already documented optional SDK/PDF/image requirements.

A normal reviewed source revert restores the earlier alias and error behavior;
preserve the dated observations and complete rate/assistance snapshots. No user
database or account state is changed. Update the resolver, core, MCP description
and review-package fingerprint together. No published release, running service,
assistance enrollment or production rollout was changed by this draft.
