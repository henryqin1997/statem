# TB3 v4p82 UAutomizer x86 direct result

## Result

- Evidence class: adapted platform calibration, not fresh score.
- Raw reward: `0.0`; reward and protocol valid.
- Errors / retries: `0 / 0`.
- Model / agent: GPT-5.6 Sol max, direct baseline-v2, Codex `0.149.1`.
- Cost: `$4.095926`.
- Tokens: 7,285,807 input; 7,113,984 cached; 28,152 output.
- Wall time: about 39 minutes 50 seconds.
- ATIF: `ATIF-v1.5`, 83 steps; raw-session paths absent.

The x86 Docker environment, solver, artifact transfer, and verifier all
completed normally. The prior ARM-only runtime confound is therefore closed,
but removing it did not convert the task.

## Local attribution

The exact x86 artifact is a third distinct JAR. Compared with both the original
ARM direct artifact and the v4p75 adapted artifact, only
`BitabsTranslation.class` differs. All three artifacts scored raw zero. The
existing public semantic matrix passed only through an alternate compatible
invocation and did not distinguish any pair, so it remains advisory evidence
rather than a candidate-bound acceptance gate.

No new candidate-blind public oracle is available from this run. Freeze the
conclusion at task scope, reject family/global promotion, and park UAutomizer.
Another adapted cell is admissible only after an independently specified public
discriminator can produce different predicted observations for competing
implementations before either candidate is inspected.

## Preservation

- Remote/local regular files: `14 / 14`.
- Remote/local bytes: `1,872,359 / 1,872,359`.
- Deterministic relative-path/content tree SHA256:
  `fa2372679a14626ac13bfd159a0b08866a51779b88901b936c621097025cdcd0`.
- Remote-to-local checksum dry-run: empty.
- Runner, Harbor, verifier, tmux session, and task containers: exited.

Backup:
`.statem/benchmarks/backups/tb3-sol-native-baseline-v2-uautomizer-v4p82-k1-aws-x86-a`
