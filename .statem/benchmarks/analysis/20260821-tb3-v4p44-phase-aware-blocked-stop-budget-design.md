# TB3 v4p44 phase-aware blocked-transition Stop budget

## Evidence basis

The adapted v4p43 Heat cell produced one `solve -> falsify` block with a stable
`acceptance_plan_gap` fingerprint and immediate `test_planner` ownership. Its
archive contains a mechanically coherent repaired acceptance plan, proposal,
candidate replay, and immutable baseline/candidate snapshot binding. The
candidate replay completed with one pass and one failure, but the lifecycle
history contains no second transition attempt and the job ended
protocol-invalid in `solve`.

The entry-scoped Stop receipt reached continuation count two with a configured
base allowance of one. The first continuation occurred before the blocked
transition while preflight work was still being joined. A single static budget
therefore conflated preflight lifecycle with post-block repair lifecycle.
Increasing the allowance for every entry would add unnecessary work and
negative-transfer risk on tasks that never block.

## Minimal control

v4p44 adds one optional StateM Stop-hook parameter:

`STATEM_STOP_EXTRA_CONTINUATIONS_AFTER_GOTO_BLOCKED`

The default is zero, so existing adapters and core behavior are unchanged.
When enabled, the hook reads the durable current run state and grants the extra
budget only if history contains `goto_blocked` for the exact current entry.
Prior-entry blocks do not carry over. The continuation reason tells the same
context to preserve passing evidence, repair the exact failed gate, and rerun
that transition without creating another candidate or weakening the gate.

The v4p44 adapter retains v4p43's base allowance of one and enables exactly one
blocked-transition slot. Blocker-fingerprint dominance, session no-progress
limit, candidate/review budgets, runbook, family router, promotion gate, and
task practices remain unchanged. A repeated unchanged blocker still fails
closed.

## Validation

- Focused Stop-hook, recovering-develop, and failure-closure suite: 79 passed.
- The focused hook tests prove:
  - base budget one remains one before any block;
  - one additional slot appears after current-entry `goto_blocked`;
  - the next stop is denied after that slot is consumed; and
  - a block from another entry grants no additional slot.
- Strict validation of the unchanged v4p35 runbook: passed.
- Ruff check of all changed Python files: passed.
- Codex remains pinned to `0.148.0`.
- Adapter identity:
  `ziheng-yaxin-statem-codex-evidence-develop-v4p44-exp`.
- Canonical deployment source manifest: 36 files,
  `a3cc723ed13a0fabb7de09ce573562b441dce9ca9f7a002b11be529c57b1f230`.
  The isolated worktree has the same 36 file-content digests but a different
  aggregate hash because the public manifest also binds its worktree basename
  as `source_root`.

The isolated worktree lacked several unrelated untracked example fixtures that
exist in the primary worktree, so six broad CLI tests failed before reaching
the changed code. After the active local direct job exited and the change was
applied to the primary worktree, full validation passed: 750 tests passed, 3
skipped, and 78 subtests passed. Strict validation of the unchanged runbook
also passed in the canonical deployment tree.

## Promotion rule

First repeat one adapted Heat mechanism cell. Success requires either:

1. the repaired current-entry gate is retried and the state advances; or
2. the retry records a changed or repeated blocker and terminates with a
   complete bounded receipt.

Separately run a previously passing sentinel to detect added wall-time or route
regression. This adapted evidence never counts toward the fresh score ledger.
Only after mechanism success and no sentinel regression may a frozen fresh
StateM arm use v4p44.
