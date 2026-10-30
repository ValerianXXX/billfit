# Bill parser cancellation and admission

Observed October 30, 2026. This development change is stacked on the bill-input
evidence repair; it is not a release, deployment or tariff activation.

## Problem and behavior

The optional MCP SDK handler previously executed the synchronous bill parser
inside its async handler. While a parser waited for a child, the event loop could
not answer another tool request or process a cancellation notification. A local
parser deadline did not make the MCP cancellation boundary responsive.

The SDK handler now dispatches bill extraction to an AnyIO worker. A small
standard-library `bill_cancellation.py` binds a request-local checkpoint to the
SDK cancellation scope. Checkpoints run before spawning a child, while waiting
for it, between source/field processing steps and before returning candidates.
Cancellation propagates as cancellation, rather than an error-shaped success.
The worker is not abandoned: its existing cleanup reaps its owned child and
removes its private snapshot before releasing the parser slot.

Each SDK server instance admits two bill extractions. A third request receives
a structured tool error with code `BILL_PARSER_BUSY`; it is not queued and does
not create another bill snapshot. A cancelled or failed extraction releases its
slot. Cancelling one request leaves the other active request alone. No additional
tool argument, dependency, model, cloud upload or calculator behavior is added.

## Fixed comparison and actual interface evidence

The five initial contracts were committed before implementation at
`b1dc06000a36043389bb38e27b29c3eb1b61ea1f`. The unchanged baseline failed all five:
three missing cancellation-interface errors and two actual SDK timeouts while a
slow synthetic extraction blocked a scope request. The original logs remain
recorded by hash; they are not converted into passes.

| Check | Before | After |
| --- | --- | --- |
| Already-cancelled request | No cancellation interface | No child starts |
| Running owned child | No cancellation interface | Child reaped; next request works |
| Cancellation after parser output | No cancellation interface | No candidates returned; source unchanged |
| Modern SDK, mode 2026-07-28 | Scope request times out after two seconds | Scope responds, third parser rejected, cancellation cleans up, same connection recovers |
| Legacy SDK, negotiated 2025-11-25 | Same responsiveness timeout | Same cancellation/admission/recovery contract passes |

The initial five tests pass in 5.305 seconds after implementation. Two additional
scenarios then verify request isolation in each SDK mode: cancel one of two slow
parsers, confirm the second remains active, successfully parse the committed
two-page PDF using the released slot, then cancel the remaining slow request.

The complete local optional-profile suite passes **124 tests in 27.082 seconds,
with no skips**, on Windows Python 3.11.3, MCP SDK 2.3.0 and pypdf 6.21.3.
The existing 117-test baseline passed before editing. Dependency validation also
passes. CI explicitly reruns cancellation contracts after installing optional
profiles, so its initial standard-library run is not the only coverage.

These tests use real SDK client/server stdio and owned local Python children.
Only the long-parser fixture is synthetic; a later request uses the actual
committed PDF and pypdf worker, preserving ten unconfirmed candidates. Assertions
bound responsiveness and cleanup; these single observations are not latency
benchmarks. They do not validate new Hermes/model-selected cancellation behavior,
real customer files, native Tesseract cancellation or independent human use.
No model request was made and no inference-cost saving is claimed.

The [receipt](../reports/parser-cancellation-verification-20261030.json) records
the source commit, portable source hashes, local log hashes and test boundaries.
Earlier OCR observations remain unchanged: skew and rotation still fail, with
no new field-recall result from this milestone.

## Run and recover

Use the Python environment configured for the MCP host:

```shell
python -m pip install -r plugins/billfit/requirements-agent.txt -r plugins/billfit/requirements-bill-input.txt
python plugins/billfit/skills/billfit/scripts/mcp_server.py --sdk
```

Configure that interpreter, script and `--sdk` in Hermes or another compatible
host's stdio server entry. The script reads MCP messages from stdin; it is not an
interactive bill prompt. Keep the existing exact `bill_file` argument and
trusted `BILLFIT_TESSERACT_PATH` configuration for optional images.

The client cancels the outstanding tool request using its SDK/protocol support.
Treat cancellation as an incomplete operation, not verified fields. On
`BILL_PARSER_BUSY`, wait for completion or cancellation before retrying; do not
automatically loop or launch another server to bypass admission.

Reproduce the no-credential synthetic contracts and full regression:

```shell
python -m unittest discover -s plugins/billfit/tests -p test_parser_cancellation.py -v
python -m unittest discover -s plugins/billfit/tests -v
```

## Boundaries and reference checks

- The two-slot limit belongs to one SDK server instance, not all processes on a
  machine. A hard decoder memory limit and cross-server admission remain open.
- Checkpoints are cooperative. Slow filesystem operations or an uninterruptible
  native call are not given a new hard cancellation deadline. Child timeout and
  output limits remain as documented in the input guide.
- Only the directly owned parser child is controlled; no process-name scan or
  arbitrary process termination is added. Trusted executable requirements remain.
- Other synchronous calculation/usage tools are not moved into this worker path.
- The default stdlib legacy shim remains synchronous and does not gain request
  cancellation. A protocol version-string change alone would not fix it.
- Bill candidates remain unconfirmed, source hashes remain checked and tariff
  verification stays dated October 27. No source value or eligibility is inferred.

Official references checked on October 30:

- [MCP Python SDK cancellation](https://py.sdk.modelcontextprotocol.io/handlers/cancellation/):
  synchronous worker code needs cooperative `anyio.from_thread.check_cancelled()`
  checkpoints; cancellation must preserve cleanup.
- [SDK cancellation migration behavior](https://py.sdk.modelcontextprotocol.io/migration/#cancelled-requests-are-no-longer-answered):
  a cancelled request should not be reported as a successful completed tool call.

The installed SDK's request dispatcher was also checked. No external product
source was copied; the pinned SDK version is unchanged.

## Review and rollback

Review the source change independently over the bill-input repair. There is no
database migration, new persistent state, account action or production change.
Restore the prior source with an ordinary reviewed revert if necessary; retain
the original fixtures and before/after observations. The previous source restores
the known blocking cancellation behavior, so it is not an equivalent validated
fallback. No main merge, release or host installation is performed here.
