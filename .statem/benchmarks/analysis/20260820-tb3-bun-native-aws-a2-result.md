# TB3 Bun Native AWS x86 k=1 Result

## Result

- Job: `tb3-sol-native-baseline-v1-bun-sourcemap-leak-k1-aws-x86-a2`
- Task: `terminal-bench/bun-sourcemap-leak`
- Role: native direct half of the predeclared AWS x86 matched k=1 pair
- Raw reward: **0.0**
- Reward validity: valid standard-timeout raw observation
- Protocol validity: valid
- Errors / retries: 0 / 0
- Model: GPT-5.6 Sol, max reasoning
- Codex: 0.148.0
- Agent: `codex-auth-no-session-baseline-v1`
- ATIF: v1.5, 36 steps
- Input / cached / output tokens: 973,242 / 892,928 / 33,691
- API cost: **$1.858764**
- Wall time: 990.883 seconds
- Raw-session directories: 0

The earlier `-a` launch was startup-invalid because the native harness module
had not been deployed on the host. This replacement started only after the
harness was deployed and independently validated. The invalid launch remains
preserved and excluded from reward accounting.

## Preservation

- Remote source regular files: 24
- Local backup regular files: 24
- Remote source bytes: 294,482
- Local backup bytes: 294,482
- Deterministic relative-path tree SHA256, both copies:
  `a9fc369c63436f14ce1f30263a0edd409d2ee9552459d6d2613df276aaaba7fc`

The matching v4p33 StateM x86 cell was still active when this report was
recorded. This direct result therefore establishes only the baseline half; it
does not establish a StateM gain or a pass-rate estimate.
