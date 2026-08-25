# TB3 v4p83 Layout Config AWS direct result

## Result

- Evidence class: fresh direct infrastructure replacement, protocol invalid.
- Raw reward: none; the trial reward is null. The aggregate `0.0` metric is not
  reward-valid.
- Error / retries: `AgentTimeoutError / 0`.
- Model / agent: GPT-5.6 Sol max, direct baseline-v2, Codex `0.149.1`.
- Cost: `$9.222037`.
- Tokens: 16,110,489 input; 15,839,872 cached; 90,181 output.
- Agent time: 3,600 seconds; wall time: about 73 minutes 31 seconds.
- ATIF: `ATIF-v1.5`, 149 steps; raw-session paths absent.

The AWS replacement crossed the earlier Daytona environment-start boundary and
reached normal solver execution. The solver hit the standard one-hour deadline
before verifier handoff. Declared public output artifacts were collected, but
without verifier execution they cannot establish correctness or a raw zero.

## Attribution

This is deadline/protocol evidence, not a task-control result. Do not extract a
family practice or count it in the fresh numerator. A later extended diagnostic
is admissible only if it is preregistered as non-score evidence and can measure
whether the existing artifact is complete enough to justify more solver time.

## Preservation

- Remote/local regular files: `23 / 23`.
- Remote/local bytes: `8,803,498 / 8,803,498`.
- Deterministic relative-path/content tree SHA256:
  `8b1abf63594887755a6afcd87a4122f4a6e53ca6313ad4a155722a01248d1c30`.
- Remote-to-local checksum dry-run: empty.
- Runner, Harbor, verifier, tmux session, and task containers: exited.

Backup:
`.statem/benchmarks/backups/tb3-sol-native-baseline-v2-layout-config-v4p83-k1-aws-x86-a`
