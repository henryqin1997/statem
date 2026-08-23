# TB3 v4p62 MVCC thin-family sentinel result

Date: 2026-08-23

## Result

- Task: `terminal-bench/mvcc-lsm-compaction`
- Cell: adapted known-positive negative-transfer and family-admission sentinel
- Raw reward: `1.0`
- Reward validity / protocol validity: `true` / `true`
- Errors / retries: `0` / `0`
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-thin-family-v4p62-exp`
- Codex: `0.149.0`
- Cost: `$1.0312304`
- Input / cached / output tokens: `914,048` / `825,856` / `17,406`
- Total wall time: about `12m42s`; agent execution about `9m10s`
- ATIF: real `ATIF-v1.5`, 41 steps
- Final StateM state: `handoff`
- Source manifest: 10 files,
  `82239b696d02f50fa848064438d7cf1b809540f9f9d4aa46017f38e0815afaf0`
- StateM export contains no raw session artifact. Standard Harbor trajectory
  artifacts remain outside the StateM export.

This is adapted mechanism evidence only. It is not a fresh holdout and adds
nothing to the fresh score numerator.

## Routing and context

The selector used only the visible instruction and produced exactly one match:

- family: `stateful-lifecycle`
- practice: `stateful_lifecycle_compact`
- trigger groups: `mvcc` and `visibility`
- activation: `active` for this explicitly adapted cell
- maturity: `family_candidate`, `admitted: false`

The solver received the three compact obligations and one stop rule. Detailed
reviewer checks were represented only by a hash in the selection receipt and
were not injected into solver context. The source manifest contained core,
the 86-line thin runbook, deadline and stop-hook support, and the single
practice catalog; no v4p61 reviewer, promotion, provider, or heavy evidence
stack was loaded.

## Repair trace

The durable StateM path was:

`solve -> verify -> solve -> verify -> self_review -> handoff`

The first verification therefore caused a local same-context revision. The
second verification advanced to one bounded self-review and handoff. There was
no quarantine, rollback, independent reviewer graph, nested child runbook, or
second family. This is live evidence for the intended distinction:

- recoverable local evidence uses **Revise**;
- no high-level falsification required **Rebranch**;
- no destructive or provenance-invalid condition justified **Rollback**.

## Descriptive comparison

All comparison cells are adapted and stochastic. v4p61 ran on remote x86 with
Codex 0.148.0, while v4p62 ran on local ARM with Codex 0.149.0, so the deltas do
not isolate a single causal variable. They are still strong admission evidence
because reward and protocol validity were preserved while the heavy control
surface was removed.

| Metric | v4p57 | v4p61 | v4p62 thin |
| --- | ---: | ---: | ---: |
| Raw reward | 1.0 | 1.0 | 1.0 |
| Cost | $7.084132 | $11.610926 | $1.031230 |
| Wall time | 26m07s | 48m04s | 12m42s |
| Input tokens | 9,474,344 | 16,991,080 | 914,048 |
| Output tokens | 43,474 | 56,253 | 17,406 |
| ATIF steps | 116 | 163 | 41 |
| Manifest files | 37 | 37 | 10 |

Against v4p61, v4p62 reduced cost by 91.1%, wall time by 73.6%, input tokens
by 94.6%, output tokens by 69.1%, and ATIF steps by 74.8%. Against the local
ARM v4p57 cell, it reduced cost by 85.4% and wall time by 51.4%.

## Preservation

- Source / backup regular files: `40` / `40`
- Source / backup bytes: `330,252` / `330,252`
- Deterministic relative-path/content tree SHA-256, both copies:
  `c0c4cc5e2a90e0b64126ab355abf60bcf6dfd2940745251285980497553ee88b`
- `rsync -nrc --delete`: empty
- Exact launchd label: unloaded
- Runner, Harbor, and experiment containers: exited

Backup:
`/Users/qinziheng/workspace/statem/.statem/benchmarks/backups/tb3-sol-thin-family-v4p62-mvcc-negative-transfer-k1-local-arm-b`

The earlier `arm-a` launch failed before model execution because the Harbor
runner was bound to the main repository instead of the frozen worktree. It had
no raw trial or API cost and is separately preserved as startup-invalid: 5
files, 7,151 bytes, tree SHA
`af289bf3478144ba9b2cdc91979054835639aff0b4ca6a22c39131c7aaf6b025`.

## Disposition

This single sentinel admits the **thin architecture** and compact-only context
boundary as the next development baseline. It does not yet admit the
stateful-lifecycle practice as a general scoring control. Keep the selector
shadow by default and require at least one family-transfer cell plus a weak-
signal false-positive sentinel before active family admission.
