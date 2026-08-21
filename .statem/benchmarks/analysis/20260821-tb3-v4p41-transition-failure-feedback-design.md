# TB3 v4p41 transition-failure feedback closure

## Failure owner

The v4p40 risk sentinel repeatedly reached the same blocked
`solve -> falsify` transition. The machine gate emitted a precise failure:
the candidate-blind acceptance plan had not appended the exact prior
validation delta. The same-context recovery prompt did not carry that output,
so the lead solver was told only to inspect the current node and continue.

This is a host lifecycle feedback defect. It is not a task-family practice,
reviewer verdict, or reason to weaken the gate.

## Minimal repair

v4p41 leaves the shared v4p35 runbook and family router unchanged. The host
adapter now materializes a bounded receipt for the latest blocked transition
in the current StateM entry and includes its first-line summaries in the next
same-session recovery prompt. The prompt requires the lead to repair the exact
failed gate, preserve passing obligations, update the owning artifact or
validation plan, rerun the public gate, and avoid an unchanged transition.

The receipt is capped at four blocking checks and 500 characters per summary.
SHA-256 values and UUIDs are redacted. It cannot rewrite reviewer evidence,
change a verdict, bypass a transition, promote a candidate, or allocate an
extra retry. The existing machine gate remains authoritative.

## Validation

- Focused failure-closure, recovery, and promotion tests: 99 passed.
- Full repository suite: 732 passed, 3 skipped, 78 subtests passed.
- Strict validation of the unchanged v4p35 runbook: passed.
- Codex remains pinned to 0.148.0.
- Adapter identity: `ziheng-yaxin-statem-codex-evidence-develop-v4p41-exp`.
- Candidate source manifest: 36 files,
  `0d204b2414ff0633fe2cd41547638423a714d8660f6becbf24755a07f62ace6f`.

v4p41 is a candidate only. v4p39 remains the last validated adapter until a
fresh risk-scorer sentinel demonstrates raw and protocol non-regression.
