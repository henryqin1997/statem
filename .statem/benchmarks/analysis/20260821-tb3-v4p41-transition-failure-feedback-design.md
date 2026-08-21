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
- The prelaunch analysis originally recorded source manifest
  `0d204b2414ff0633fe2cd41547638423a714d8660f6becbf24755a07f62ace6f`.
  That value was stale tracking metadata. The manifest embedded at launch and
  an independent rebuild from the idle remote source both contain 36 files
  and SHA-256
  `4b1ee166534ae7a7f87345790568c541e8eb2d73c87c00d3a3385dfcefa1b54f`.

## Sentinel outcome

The repeated risk-scorer sentinel completed with raw reward `1.0`, no
exception, ATIF-v1.5, exact agent/model/version identity, stable 36-file source
manifest, bound candidate replay, verified quarantine application, and final
StateM state `handoff`. It therefore supplies raw and protocol non-regression
evidence.

It does not validate the new mechanism itself. The run recorded zero host
session resumes and exported no `transition-failure-feedback.json` receipt, so
the v4p41 feedback path was never exercised. Wall time was 5,714 seconds and
cost was $29.464298, versus 3,042 seconds and $12.762398 in the prior v4p39
sentinel. One stochastic pair cannot causally assign that increase to v4p41,
but it also cannot justify activation.

v4p41 is therefore not promoted. v4p39 remains the validated adapter, and the
transition-feedback change stays available for a future matched cell that
actually produces the bounded receipt.
