# ESPI reading meaning: frozen protocol, 1 November 2026

The current parser accepts one ReadingType and its energy unit/multiplier but
does not enforce its declared direction, accumulation, commodity or measurement
kind. A positive exported value can therefore become imported consumption.

Freeze the synthetic cases, generator and API/SDK contracts before runtime edits.
Run the same cases through the actual CLI before and after. Report unsupported
inputs admitted, unresolved metadata/quality hidden, and supported controls lost
separately; do not call this real-bill accuracy or certification.

Reject explicitly incompatible meanings and ambiguous/invalid metadata. Keep
legacy incomplete files readable with an explicit review requirement; missing
meaning must not establish annual savings or validate a matching bill. Respect
an interval's declared quality over the ReadingType default, retain multiple
flags and flag unspecified or non-final quality for review. Do not infer export
direction from a positive number or convert cumulative registers by guessing a
previous reading. Source bytes, all tariff snapshots and current tests remain.

Use the existing deterministic calculator and stdlib CLI; add no model, cloud
account, parser dependency or active tariff. The ordinary single-meter,
non-solar import scope stays in force. Test both supported SDK client modes and
same-connection recovery, plus a complete 28-day series and arithmetic-matching
bill that still requires review. Perform the complete existing test suite once
the implementation is stable.

Official references inspected on 1 November 2026:

- [GBA schema view](https://dev.greenbuttonalliance.org/espiusecase.html), visibly
  version 3.3.20190408; not asserted to be the newest ESPI revision. Its direction
  codes distinguish positive forward import from positive reverse export.
- [GBA multiplier example](https://www.greenbuttonalliance.org/poweroftenmultiplier):
  incremental electric energy with forward direction and Wh-based scaling.
- [GBA reading-quality explanation](https://www.greenbuttonalliance.org/accuracy):
  interval quality overrides a default; multiple flags can coexist.

These references define input interpretation, not an official PG&E bill outcome.
No external source code is copied. No provider calls or real customer data are
used. Preserve the existing unresolved Saturday holiday-observance and exact
utility-rounding questions separately from this parser change.
