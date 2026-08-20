# TB3 v4p33 Bun AWS x86 Result

## Result

- Job: `tb3-sol-evidence-v4p33-bun-sourcemap-leak-k1-aws-x86-b`
- Raw reward: unavailable
- Reward validity: invalid; verifier was not reached
- Protocol validity: invalid; final StateM state was `revise`, not `handoff`
- Error: `RuntimeError`, no retry
- Cost: **$6.704198**
- Input / cached / output tokens: 5,944,054 / 5,561,856 / 67,076
- Wall time: 1,865.584 seconds
- Model / Codex: GPT-5.6 Sol max / 0.148.0
- Adapter: `ziheng-yaxin-statem-codex-evidence-develop-v4p33-exp`
- ATIF: v1.5, 88 steps
- Source manifest: 35 files,
  `e7aa59496560ade7804be5e18326ddb2273ee2c8d042fa95ca2208e25b530402`
- Family: `structured-transformation`; primary `parsing-transformation`;
  secondary `security-protocols`, `stateful-systems`
- Raw-session directories: 0

This independent x86 cell reproduced the local control path:
`solve -> falsify -> revise`, followed by protocol-invalid termination before
handoff. The family receipt again reserved 2,100 seconds for retry work inside
an 1,800-second standard budget. Cross-platform replication makes
activation/lifecycle budgeting the current dominant owner; it does not support
a hardware explanation.

## Preservation

- Remote source / local backup files: 111 / 111
- Remote source / local backup bytes: 2,838,388 / 2,838,388
- Deterministic relative-path tree SHA256, both copies:
  `52c49c5f2515492274a09e26bd01129e97d4c83e053b2be137f7834819f48c40`

This task becomes adapted for any control authored from this failure and cannot
serve as that control's final holdout.
