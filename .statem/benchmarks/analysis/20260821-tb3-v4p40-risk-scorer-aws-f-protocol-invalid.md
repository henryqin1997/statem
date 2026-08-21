# TB3 v4p40 risk-scorer sentinel result

## Status

This repeated negative-transfer sentinel is **reward-invalid and
protocol-invalid**. It produced no verifier reward and does not contribute to
the phase-one score estimate. The v4p40 candidate control is not promoted;
v4p39 remains the last validated adapter.

## Configuration validity

- Task: `terminal-bench/risk-scorer-replay`
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p40-exp`
- Model: `gpt-5.6-sol`, max reasoning
- Codex: `0.148.0`
- ATIF: `ATIF-v1.5`, 342 steps
- Source manifest: 35 files,
  `5dc788d466cda29676eafa105f781f865d53217341c992608b3f82479fb10478`
- Runbook remained `examples/frontier-bench-agent-evidence-develop-v4p35-exp.yaml`
- Raw session files: 0

## Result and attribution

The run reached two solve cycles, two independent falsification cycles,
quarantine, and final replay before entering one information-gain recovery
cycle. The second solve entry produced a bound candidate, complete preflight
review, solver-recorded public evidence, and passing adapter-owned replay. The
solve-to-falsify gate nevertheless rejected the transition because the new
candidate-blind plan did not append the exact prior validation delta.

The blocker then repeated without state or progress change. Four host resumes
all remained in `solve`, and Harbor reported `RuntimeError: statem final state
is 'solve', expected 'handoff'`. This is the same failure-closure class seen in
v4p37, not a hardware limit and not the new deadline-quarantine authorization
path. It supplies no new generic progress, so the control is fail-closed.

Observed aggregate accounting was 446,639 input tokens, 440,832 cached tokens,
1,494 output tokens, and `$0.294271`. These are Harbor-recorded top-level
figures and may not include every nested reviewer accounting surface.

## Preservation

- Remote source and local backup regular files: 193
- Remote source and local backup bytes: 9,491,306
- Deterministic relative-path, size, and file-digest tree SHA256:
  `fd199be423648cf0ac77b05ef5db423f6f0edd82e83a5d0901510ed2742f8d4c`
- Raw session files: 0
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p40-risk-scorer-replay-k1-aws-x86-f`
