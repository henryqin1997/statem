# TB3 risk scorer v4p38 AWS regression result

## Cell

- Job: `tb3-sol-evidence-v4p38-risk-scorer-replay-k1-aws-x86-d`
- Role: repeated adapted k1 regression sentinel; never score eligible
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p38-exp`
- Configuration: AWS x86_64 CPU, standard timeout, no retries, no upload

## Result

- Raw reward: **1.0**
- Reward validity: valid
- Protocol validity: **invalid**
- Protocol error: ATIF records Codex `0.149.0`, while the admission contract and
  matched direct baseline require Codex `0.148.0`
- API cost: **$24.481477**
- Input / cached / output tokens: 32,609,849 / 32,039,424 / 186,988
- Wall / agent execution time: approximately 4,704 / 4,646 seconds
- ATIF: v1.5, 298 steps
- Source manifest: 35 files,
  `105d1db1dc405b2643d989407a72777d82ce11fc869290f0a5b96689784bf46e`
- Raw-session files: 0

## Mechanism evidence

The semantic-blocker lifecycle repair completed the full StateM path without a
host resume:

`contract_audit -> solve -> falsify -> revise -> falsify -> quarantine -> final_replay -> handoff`

The first independent review routed a repairable candidate to revision. The
revised candidate received a second independent review; review-budget
exhaustion then quarantined the exact candidate instead of rolling back or
opening a partial third review. Candidate-bound final replay completed and the
recovery guard authorized handoff. Runtime transition checks accepted the
contract, preflight, review, application, validation-delta, and replay
receipts. `session_resume_attempts` remained zero, and no repeated transition
blocker appeared.

This is strong reward and lifecycle evidence for v4p38. It is not a valid
negative-transfer gate because the installed Codex release drifted from the
matched protocol. The fresh data-anonymization StateM half remains unsigned.

## Generic repair

The version belongs at the adapter boundary, not in an operator convention.
v4p39 pins Codex `0.148.0`, rejects any conflicting caller value, and leaves
the runbook, task contract, reviewer semantics, promotion policy, and rollback
policy unchanged. A new repeated risk sentinel is required before a fresh
score cell can launch.

## Preservation

- Remote source and local backup regular files: 157
- Remote source and local backup bytes: 6,768,049
- Deterministic relative-path tree SHA256, both copies:
  `1a9ae68cce89fe249afbc6cd4a37c7a17ed7e669b3800fd4b90664792f6a36cd`
- Remote runner, Harbor process, reviewer/probe process, and experiment
  container absent
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p38-risk-scorer-replay-k1-aws-x86-d`
