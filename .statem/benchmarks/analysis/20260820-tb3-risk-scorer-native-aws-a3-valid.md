# TB3 risk-scorer direct replacement a3

## Cell

- Job: `tb3-sol-native-baseline-v2-risk-scorer-replay-k1-aws-x86-a3`
- Role: valid native direct k=1 half of the regression-sentinel pair
- Model: GPT-5.6 Sol, max reasoning
- Agent: `codex-auth-no-session-baseline-v2`
- Configuration: AWS x86 CPU, standard timeout, no retries, no upload

## Result

- Raw reward: **1.0**
- Reward validity: valid
- Protocol validity: valid
- Errors / retries: 0 / 0
- Input / cached / output tokens: 4,895,077 / 4,732,160 / 62,674
- API cost: **$5.060885**
- Wall interval: 2026-08-20 17:40:09Z to 18:05:05Z
- ATIF: v1.5, 77 steps
- Codex: 0.148.0
- Raw-session files: 0

This is the first valid replacement after the non-root authentication ownership
repair. The earlier a2 cell was stopped for an experiment-identity mismatch and
is not combined with this result.

## Decision

The direct sentinel establishes a valid raw-one baseline. The next admitted
cell is the exact-platform StateM control half. It is a repeated regression
sentinel, not a fresh score candidate: its purpose is to detect negative
transfer before any v4p36 family control is promoted.

## Preservation

- Remote source and local backup regular files: 30
- Remote source and local backup bytes: 717,510
- Deterministic relative-path tree SHA256, both copies:
  `1c158c532acc415eb5f889ab22bdb01dec126ccb928d889e4db0943fd108cf3f`
- Runner, Harbor, and task container exited
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-native-baseline-v2-risk-scorer-replay-k1-aws-x86-a3`
