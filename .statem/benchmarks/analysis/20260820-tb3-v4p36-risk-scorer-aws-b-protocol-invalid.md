# TB3 risk scorer v4p36 AWS regression result

## Cell

- Job: `tb3-sol-evidence-v4p36-risk-scorer-replay-k1-aws-x86-b`
- Role: adapted k1 regression sentinel; never score eligible
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p36-exp`
- Configuration: AWS x86_64 CPU, standard timeout, no retries, no upload

## Result

- Raw reward: unavailable
- Reward validity: invalid because verifier handoff was never reached
- Protocol validity: invalid
- Terminal error: StateM ended in `falsify`, not `handoff`
- API cost: **$0.424777**
- Input / cached / output tokens: 554,885 / 541,184 / 2,856
- ATIF: v1.5, 203 steps
- Codex version validation: invalid; the result field contains a bootstrap
  warning instead of a version string
- Source manifest: 35 files,
  `d4f1995d67683b336b79bb03a7906070c44fdd10c58b1307c3fc6291b70e6c4d`
- Raw-session files: 0

## Attribution

The candidate and its exact acceptance replay completed before independent
review. On entry to `falsify`, review-open and bounded context generation passed.
Falsifier-task rejected the canonical `plan_preflight_evidence` receipt because
it required the obsolete kind `preflight_evidence`; TeamRun initialization then
failed because no task file had been produced. Four bounded resumes could not
repair a host schema mismatch, and verifier execution never began.

This independently reproduces the HTML/JS lifecycle failure on x86. It is not a
raw regression against the preserved direct 1.0 result. It does fail the k1
promotion gate, so no new score-eligible StateM cell may launch until the shared
mechanical repair is validated. The malformed Codex version metadata is reported
separately and provides another reason this cell cannot validate promotion.

## Preservation

- Remote source and local backup regular files: 107
- Remote source and local backup bytes: 2,851,059
- Deterministic relative-path tree SHA256, both copies:
  `959b967443c312abc2190f0fbf8c55bc25f520b4b80b0d578284479bfbe1bdc4`
- Remote runner, Harbor process, and experiment container absent
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p36-risk-scorer-replay-k1-aws-x86-b`
