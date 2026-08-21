# TB3 risk scorer v4p39 AWS regression result

## Cell

- Job: `tb3-sol-evidence-v4p39-risk-scorer-replay-k1-aws-x86-e`
- Role: repeated adapted k1 regression sentinel; never score eligible
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p39-exp`
- Configuration: AWS x86_64 CPU, standard timeout, no retries, no upload

## Result

- Raw reward: **1.0**
- Reward validity: valid
- Protocol validity: **valid**
- Errors / retries / host resumes: 0 / 0 / 0
- API cost: **$12.762398**
- Input / cached / output tokens: 15,740,488 / 15,347,456 / 104,117
- Wall / agent execution time: approximately 3,042 / 2,987 seconds
- ATIF: v1.5, 174 steps
- Codex: 0.148.0
- Source manifest: 35 files,
  `94e67ccb1ac85a73fc2acccaa327c07608a2c17c62f41d1ced478348a8dcc92e`
- Raw-session files: 0

## Mechanism evidence

The version-pinned control completed the StateM path without a host resume:

`contract_audit -> solve -> falsify -> revise -> falsify -> quarantine -> final_replay -> handoff`

The selected family was `numerical-model` with the `ml-model-artifacts`
review profile. The first independent review found a repairable hard-contract
gap and routed the exact candidate to revision. The second review remained
inconclusive at the review budget, so the adapter quarantined the candidate
instead of rolling back or opening an unbounded review. Candidate-bound final
replay passed and authorized handoff.

One final-replay transition was initially blocked because the replay draft used
the wrong machine-readable shape for `residual_risk`; the dependent replay
decision was consequently absent. The same-context recovery repaired the
receipt, reran the checks, and completed handoff. This was a bounded,
mechanically attributable validation failure rather than a reason to discard
the artifact or restart the rollout.

The activation receipt remained in shadow `evidence_develop` mode. Artifact
application was verified in quarantine mode, the runtime accepted the repaired
review and replay receipts, `session_resume_attempts` remained zero, and the
ATIF agent record confirms Codex 0.148.0. The v4p39 raw-one sentinel therefore
passes the negative-transfer gate for one fresh matched k1 triage cell. It does
not contribute to the phase-one score estimate.

## Preservation

- Remote source and local backup regular files: 158
- Remote source and local backup bytes: 5,559,436
- Deterministic relative-path tree SHA256, both copies:
  `cab073a9fd23dfcd161dbe9ac1a4cc730c060ab22224bb16639903d4b7170d61`
- Remote runner, Harbor process, reviewer/probe process, and experiment
  container absent
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p39-risk-scorer-replay-k1-aws-x86-e`
