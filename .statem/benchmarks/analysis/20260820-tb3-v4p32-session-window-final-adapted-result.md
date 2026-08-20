# TB3 session-window v4p32 final adapted result

## Cell identity

- Job: `tb3-sol-evidence-v4p32-session-window-sentinel-k1-aws-x86-b`
- Task: `terminal-bench/session-window-debug`
- Role: second and final adapted attempt for the current control hypothesis;
  excluded from fresh score
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p32-exp`
- Model: GPT-5.6 Sol, max reasoning
- Codex: `0.148.0`
- Source manifest: 35 files,
  `1a7d5f58bd3e7cee94b347928b8f5e082c0f02fed52efbc44db44387ac4921ef`
- Route: `stateful-lifecycle` / `stateful-systems`

## Raw and protocol result

- Raw reward: unavailable; verifier did not run.
- Protocol validity: invalid. Final StateM state was `solve`, not `handoff`.
- Wall time: about 18 minutes.
- Session resumes: 2.
- Tokens: 694,889 input, 680,704 cached input, 1,583 output.
- API cost: $0.458767.
- Trajectory: ATIF-v1.5, 96 steps, including 57 aggregate `exec` calls.
- Raw Codex session directories retained: 0.

This cell is neither a zero reward nor a pass-rate observation.

## Mechanism attribution

The cell selected the expected family and wrote a sealed solver plan, but it
never produced preflight evidence, a candidate proposal, acceptance replay, or
promotion decision. Its only recovery cycle remained open.

The v4p32 same-entry progress control behaved as designed: repeated read-only
exploration did not change the task artifact or a bounded milestone receipt, so
it did not reset the no-progress allowance. The adapter stopped after two truly
unchanged resume witnesses rather than granting unlimited continuation.

The candidate-blind stratum-coverage gate was never reached. Therefore this
cell does not validate or falsify that gate; route selection alone is not
mechanism evidence.

Compared with the previous adapted attempt, this run added no new reproducible
discriminator, narrower failure owner, bound validation delta, or public
artifact/check improvement. Under the predeclared two-attempt policy,
`session-window-debug` is now parked. The dominant unresolved limit is task
execution/base-model or orchestration burden before candidate formation, not a
known host lifecycle defect. Reopening requires a new generic hypothesis from
another task, not another identical retry.

## Preservation

- Remote and local backup: 66 regular files, 1,662,478 bytes.
- Deterministic relative-path tree SHA256:
  `8fe2213eb7dffd93c5921e7d52b3468cf147b7f24f7c803b1646da037115c82f`
- Backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p32-session-window-sentinel-k1-aws-x86-b`
- Runner, Harbor process, and experiment container absent at backup time.
