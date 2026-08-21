# TB3 v4p41 Risk-Scorer Sentinel Result

## Outcome

- Job: `tb3-sol-evidence-v4p41-risk-scorer-replay-k1-aws-x86-g`
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p41-exp`
- Model: `gpt-5.6-sol`, Codex `0.148.0`
- Raw reward: `1.0`
- Exception: none
- Trial wall time: 5,714 seconds
- Agent time: 5,658 seconds
- Cost: $29.464298
- Tokens: 39,252,610 input, 38,428,416 cached input, 204,304 output

This repeated 5/5-prior task is a negative-transfer sentinel and contributes
no score gain.

## Protocol Audit

- Source manifest: 36 files,
  `4b1ee166534ae7a7f87345790568c541e8eb2d73c87c00d3a3385dfcefa1b54f`
- The embedded manifest equals an independent rebuild from the idle remote
  source. The earlier `0d204b24...` prelaunch note was stale metadata, not the
  source imported by this job.
- Activation selected `evidence_develop` in shadow mode.
- Family route: `numerical-model`; primary reviewer profile
  `ml-model-artifacts`, with `data-database` and `stateful-systems` secondary.
- The final candidate identity is identical across proposal, immutable
  snapshot, candidate replay, live replay result, and verified quarantine
  application.
- Candidate acceptance replay completed all three declared checks and reported
  passed.
- The second-cycle validation delta was required, applied, and bound to one
  candidate-blind requirement. Failure-closure hashes agree between the retry
  brief and validation receipt.
- Final StateM state: `handoff`.
- Trajectory: ATIF-v1.5, 396 steps; no raw-session artifact.

Reward and protocol validity are both true. The final review exhausted its
bounded review budget and selected verified quarantine rather than promotion;
final replay still evaluated the exact quarantined candidate.

## v4p41 Decision

The sentinel recorded zero host session resumes and exported no bounded
transition-failure feedback receipt. The v4p41-only path therefore was not
exercised. Raw reward did not regress, but wall time was 87.8% higher and cost
was 130.9% higher than the prior v4p39 sentinel. This single stochastic pair
does not establish causal performance regression, yet it provides no basis to
promote an unexercised control.

Decision: retain v4p39 as the validated adapter. Keep v4p41 experimental until
a matched transition-failure cell produces the receipt and demonstrates
same-context repair.

## Preservation

Remote source and local backup match exactly:

- Regular files: 240
- Total bytes: 12,363,391
- Deterministic relative-path, size, and content-digest tree SHA-256:
  `6bfe6df410f985b4bf42c84c4f457182ad7e00789a08583331b32f40ae534bb7`

Local backup:
`.statem/benchmarks/backups/tb3-sol-evidence-v4p41-risk-scorer-replay-k1-aws-x86-g`
