# TB3 v4p34 Deadline-Aware Review Routing

## Evidence

The local ARM64 and AWS x86 v4p33 Bun cells independently reached
`solve -> falsify -> revise`. Both then exhausted the standard 1,800-second
agent window before revise could produce a new candidate, second review, final
replay, and handoff. Their raw rewards are unavailable and their protocols are
invalid. Both complete jobs are preserved with matching source/backup tree
hashes in their individual result reports.

The falsifier found a real contract-generalization defect, so removing review
or treating the candidate as promoted would be incorrect. The owning layer is
review lifecycle scheduling: `deadline-feasible retry` existed for opening a
new recovery cycle after final replay, but no equivalent check guarded a second
review inside the current cycle.

## Control

v4p34 adds `revision_reserve_seconds` to the deterministic family receipt. The
host-owned review router receives the official deadline and family receipt.
When the promotion decision requests revise:

1. Review-budget exhaustion still quarantines as before.
2. An unconfigured deadline preserves revise behavior.
3. A configured deadline with the complete revision reserve available permits
   revise.
4. Insufficient reserve changes only the lifecycle route to quarantine, keeping
   the exact reviewed candidate isolated for final replay and handoff.

The receipt records remaining seconds, required reserve, feasibility, reason,
and whether deadline degradation occurred. Task contract, candidate identity,
reviewer verdict, promotion authority, and rollback semantics are unchanged.
Older runbooks do not pass `--require-deadline-budget` and remain compatible.

## Validation

- Focused family/failure/recovery/activation tests: 54 passed.
- Full local test suite: 707 passed, 3 skipped.
- Strict v4p34 runbook validation: passed.
- Canonical source manifest: 35 files,
  `c6ddf782bd8695e1c30dfee371e2a21d0237f3aff5bc785a8943c6cc3a557973`.

## Evaluation Plan

Run one extended-time adapted Bun diagnostic to test whether a complete revise
can close the observed validation gap. In parallel, use standard-timeout fresh
tasks for score evidence. Bun is adapted for v4p34 and cannot serve as its
holdout. Promotion still requires a same-family fresh sentinel and the matched
5/5 `risk-scorer-replay` zero-regression sentinel before matched k=5 scoring.

This control does not yet bound an unusually long first solve that fails to
reach falsification. That is a separate stage-admission question and should be
changed only if a future cell provides a reproducible pre-falsify deadline
failure.
