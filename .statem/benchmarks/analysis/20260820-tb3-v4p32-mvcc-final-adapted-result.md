# TB3 MVCC v4p32 final adapted result

## Scope

- Task: `terminal-bench/mvcc-lsm-compaction`
- Job: `tb3-sol-evidence-v4p32-mvcc-failure-closure-k1-aws-x86-a`
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p32-exp`
- Model: GPT-5.6 Sol, max reasoning
- Codex: `0.148.0`
- Platform: AWS x86_64 Docker
- Sampling: adapted k=1, standard timeout, no retries, no upload
- Family/profile: `stateful-lifecycle` / `stateful-systems`

## Outcome

The trial has no raw reward and is protocol-invalid because final StateM state
was `solve`, not `handoff`. It is excluded from score. This was nevertheless a
substantive development cell rather than another no-progress attempt.

- Cost: `$0.654156`
- Input/cache/output tokens: `752,934 / 728,832 / 5,641`
- ATIF: real `ATIF-v1.5`, 204 steps
- Source manifest: 35 files,
  `1a7d5f58bd3e7cee94b347928b8f5e082c0f02fed52efbc44db44387ac4921ef`
- Raw-session directories: 0

The same solve entry advanced through 39 durable history events and produced a
preflight receipt, candidate proposal, immutable candidate snapshot, and adapter
replay. The candidate-blind plan contained six requirements. Its executable
requirement declared both normal-regression and reduced-crash-reproduction
strata; adapter replay covered both exactly and passed both checks.

The remaining failure owner was the host receipt protocol. The reviewer emitted
uppercase mechanical ids (`AR-1`, `PR-1` through `PR-4`, and `AN-1`). The
semantic receipt and replay used equivalent lowercase ids, but the dynamic
preflight recording gate revalidated the raw reviewer result with a
lowercase-only pattern. Eight attempted `solve -> falsify` transitions were
blocked by the same invalid-id error even though candidate, snapshot, replay,
reviewer lifecycle, and other before-transfer checks passed.

This is not a reason to modify the task artifact, rerun the lead, quarantine the
candidate, or roll back. The generic v4p33 repair trims and lowercases only the
mechanical requirement id before validation, then detects duplicates on the
canonical value. Claims, evidence modes, required strata, and reviewer verdicts
remain immutable. Focused tests include uppercase normalization, case-collision
rejection, strict runbook validation, and direct replay of the preserved MVCC
reviewer result.

## Preservation

- Remote/local regular files: `105 / 105`
- Remote/local bytes: `6,205,986 / 6,205,986`
- Deterministic relative-path tree SHA256:
  `324374b9683815333b7eaeed9b14e5c697540e37095a38a29a72e69cb6366631`
- Backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p32-mvcc-failure-closure-k1-aws-x86-a`
- Runner, Harbor process, reviewers/probes, and experiment container exited.
