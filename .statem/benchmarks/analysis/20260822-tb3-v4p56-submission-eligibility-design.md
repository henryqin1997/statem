# TB3 v4p56 submission eligibility design

## Problem

The v4p55 controller separates review from promotion, but quarantine still
selects the reviewed candidate as the final evaluation target. The fresh
pretrain k1 cell made the gap concrete: review found a validated blocking
contract violation, promotion returned `revise`, acceptance replay failed, and
the candidate was correctly quarantined. The same candidate nevertheless
remained the handoff target.

This is not a reason to remove quarantine. A quarantined snapshot is useful for
diagnostic replay and attribution. It is a reason to separate three decisions:

1. whether a candidate may be promoted as retained knowledge;
2. whether it may be replayed for diagnosis; and
3. whether the currently applied artifact may be submitted at handoff.

## Minimal control

`submission_eligibility_gate.py` is an adapter-owned deterministic gate, not a
StateM core primitive. It binds the promotion decision, effective review route,
candidate acceptance replay, final replay decision, and provider application.
It emits explicit pre-replay promotion authorization, post-replay promotion
eligibility, diagnostic-replay eligibility, candidate-submission eligibility,
selected target, fallback, and handoff eligibility fields.

The optional `strict_review` policy makes every quarantined candidate
diagnostic-only. It selects the immutable baseline for submission and requires
a verified provider restore before handoff. A promoted candidate must still
pass candidate-bound acceptance and final replay before either retained
promotion or submission.

The default `deadline_best_validated` policy can submit a quarantined candidate
only when quarantine is caused by review-budget or deadline exhaustion,
review receipts are mechanically valid, no structured negative evidence
remains, adapter acceptance replay passes, and the public final replay reports
success. Unresolved or sealed evidence remains advisory for submission but
still blocks promotion into procedural memory. Falsified obligations, validated
contract violations, paired blocking regressions, observed hard gaps, or a
failed public replay force baseline restore.

## Boundaries

- The gate does not interpret task prose or verifier output.
- It does not mutate artifacts; the provider owns activate/quarantine/restore.
- Receipt hashes and run identities bind every input.
- A selected fallback is not handoff-eligible until the provider verifies the
  exact selected identity.
- The pretrain cell is an adapted regression fixture, not a holdout for this
  repair.

## Lifecycle integration

The v4p56 runbook adds two host-controlled states after final replay:

1. `submission_gate` recomputes the target from bound review, replay, and
   provider receipts. An already verified candidate or baseline may hand off.
2. `submission_restore` is reachable only when the gate selects baseline and
   explicitly reports `fallback_required`. The provider restores the immutable
   baseline and the gate recomputes eligibility before handoff.

The ordinary recoverable retry edge remains unchanged and runs before this
submission path. The handoff node independently requires both the recovery
guard's handoff action and a verified submission target.

The adapter owns the policy environment, uploads the deterministic gate, adds
its receipt to progress identity, and preserves submission receipts with the
other StateM artifacts. v4p55 remains frozen while its music and VBA cells are
active.

## Offline regression calibration

The default policy was replayed against two complete archived receipt sets:

- The fresh pretrain raw-zero cell has a falsified acceptance obligation, a
  blocking contract violation, an observed hard gap, and failed acceptance and
  public replay. v4p56 selects baseline, requires fallback, and denies handoff
  until restore is verified.
- The adapted MVCC raw-one cell has mechanically valid receipts, no structured
  negative evidence, passed candidate-bound acceptance and public replay, and
  only an unresolved advisory obligation after review-budget exhaustion. v4p56
  preserves the quarantined candidate as the verified handoff target without
  authorizing promotion.

This pair rejects both unsafe candidate submission and blanket quarantine
rollback. It is regression evidence for the control only, not fresh benchmark
score evidence.

Focused validation currently passes 111 tests across submission eligibility,
runbook lifecycle, recovery, candidate replay, and promotion. Strict runbook
validation and Python compilation also pass.
