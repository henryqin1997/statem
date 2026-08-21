# TB3 fresh score gate

## Problem

The phase-one ledger previously recorded three valid matched k=1 triage pairs
with an observed reward delta of zero. That is useful causal evidence, but it is
not a Terminal-Bench pass-rate estimate. Reporting it as `+0.0 percentage
points` would collapse two distinct claims:

1. no gain was observed in three selected k=1 trials; and
2. the full 74-task, k=5 score difference is zero.

Only the first claim is currently supported.

## Gate

`integrations/harbor/experimental/tb3_fresh_score_gate.py` validates the score
ledger outside StateM and outside task-agent context. A score-eligible pair must
explicitly bind:

- standard task and environment-build timeout multipliers;
- no retry and no upload;
- freshness for the frozen control;
- distinct allowed direct and StateM agent identities and jobs;
- valid raw rewards and protocol results;
- ATIF-v1.5 and raw-session absence;
- a terminal StateM handoff; and
- checksum-verified backup counts, bytes, and tree SHA-256 identities.

k=1 pairs are classified only as triage observations. A final score estimate
requires `final_matched_estimate`, exactly five samples per task, all 74 unique
tasks, and therefore 370 trials per agent. The +15 target additionally requires
at least 55.5 extra raw reward over those 370 matched trials. `--require-target`
returns exit code 2 until that evidence exists.

## Current receipt

- Eligible k=1 triage pairs: 3
- Observed direct reward: 0
- Observed StateM reward: 0
- Observed triage reward delta: 0
- Final estimate tasks/trials: 0 / 0
- Estimated score delta: unavailable
- Required additional reward: 55.5
- Target supported: false
- Excluded protocol-invalid pairs: Bun local, Bun AWS, and data-anonymization

The receipt is preserved at
`.statem/benchmarks/analysis/20260821-tb3-fresh-score-gate-receipt.json`.

## Validation

- Focused score/admission tests: 10 passed.
- Full suite: 737 passed, 3 skipped, 78 subtests passed.
- The current ledger validates, while `--require-target` correctly fails
  closed with exit code 2.
