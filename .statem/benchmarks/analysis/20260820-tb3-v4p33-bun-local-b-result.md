# TB3 v4p33 Bun Local ARM64 Result

## Result

- Job: `tb3-sol-evidence-v4p33-bun-sourcemap-leak-k1-local-b`
- Raw reward: unavailable
- Reward validity: invalid; verifier was not reached
- Protocol validity: invalid; final StateM state was `revise`, not `handoff`
- Error: `RuntimeError`, no retry
- Cost: **$8.731877**
- Input / cached / output tokens: 11,339,563 / 11,108,864 / 67,465
- Wall time: 1,839.399 seconds
- Model / Codex: GPT-5.6 Sol max / 0.148.0
- Adapter: `ziheng-yaxin-statem-codex-evidence-develop-v4p33-exp`
- ATIF: v1.5, 140 steps
- Source manifest: 35 files,
  `e7aa59496560ade7804be5e18326ddb2273ee2c8d042fa95ca2208e25b530402`
- Family: `structured-transformation`; primary `parsing-transformation`;
  secondary `security-protocols`, `stateful-systems`
- Raw-session directories: 0

The run made substantive protocol progress: `solve -> falsify -> revise`.
Independent falsification rejected promotion for a real contract-generalization
gap, so revise was semantically warranted rather than a receipt-schema false
block. The entry route was nevertheless deadline-infeasible: its family retry
reserve was 2,100 seconds while the standard agent budget was 1,800 seconds.
The run reached revise near the deadline and could not complete repair and
handoff. This is an activation/lifecycle budgeting defect, not a raw zero, a
hardware failure, or evidence of a base-model ceiling.

## Preservation

- Source / backup files: 126 / 126
- Source / backup bytes: 3,263,425 / 3,263,425
- Deterministic relative-path tree SHA256, both copies:
  `dcdc08297d8d8260c4ebd5561ac5573bfe1e91a8be305df94d435c305ae5b361`

This task becomes adapted for any control authored from this failure and cannot
serve as that control's final holdout.
