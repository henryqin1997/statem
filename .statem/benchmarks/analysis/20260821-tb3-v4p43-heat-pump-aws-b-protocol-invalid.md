# TB3 v4p43 heat-pump-warranty adapted result

## Result

- Job: `tb3-sol-evidence-v4p43-heat-pump-bounded-failure-k1-aws-x86-b`
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p43-exp`
- Model: GPT-5.6 Sol, max reasoning
- Codex: `0.148.0`
- Platform: AWS x86_64 Docker
- Raw reward: unavailable
- Error: `RuntimeError`
- Retries: zero
- API cost: `$2.395290`
- Tokens: 2,341,014 input, 2,236,800 cached input, 25,194 output
- Job wall time: 2,302 seconds
- Agent time: 2,249 seconds
- ATIF: `ATIF-v1.5`, 152 steps
- Raw-session-named paths: zero
- Final StateM state: `solve`

The runner, Harbor process, and all task containers exited before backup. This
is an adapted mechanism cell and is never score-eligible.

## Protocol evidence

Routing and immutable identity were valid:

- family: `stateful-lifecycle`
- primary profile: `data-database`
- source files: 36
- source manifest SHA256:
  `69e9fa807a84cfba29c5ea7930022f4b403cc064a200b3ce522492b0c63e1650`
- runbook: unchanged v4p35 evidence-develop runbook

One `solve -> falsify` transition was blocked. The v4p43 receipt classified it
as `acceptance_plan_gap`, assigned immediate ownership to `test_planner`, and
bound blocker fingerprint
`0a0dbd0fad0ff6e78779ffabe9071eb9d91f08a5b1bac13211e427747cd76160`.
The receipt recorded repeat count one and no exhausted repair budget.

The archived repair transaction is mechanically coherent:

- repair operation: remove a redundant adapter-replay mapping from the
  candidate-blind top-level acceptance plan
- eight requirement identities preserved
- candidate proposal binding preserved
- repaired plan SHA equals the live preflight acceptance-plan SHA
- live preflight SHA equals both proposal and replay bindings
- live proposal SHA equals the replay proposal binding
- immutable baseline and candidate snapshots remain distinct and verified

The candidate-bound replay completed two checks, one passing and one failing.
The public artifact manifest still recorded both declared outputs as failed
harvests, so the artifact-transaction objective did not improve.

## Attribution

v4p43 prevented the unbounded unchanged-blocker loop seen in v4p42 and produced
an owner-specific repair receipt. It did not close the transition. History
contains one blocked `goto` and no second transition attempt after the repaired
plan and rebound replay were archived. The entry-scoped Stop receipt reached
continuation count two while the configured base allowance was one; the first
continuation occurred before the blocked transition during preflight lifecycle
work.

A single static continuation budget therefore conflates two distinct phases:
joining preflight work and retrying a newly blocked transition. Increasing the
budget globally would create unnecessary work on unaffected tasks. The next
generic experiment should retain a base allowance of one and grant exactly one
additional same-context continuation only when the current entry has a durable
`goto_blocked` event. The retry must still be bounded by blocker fingerprint;
an unchanged second block fails closed. No task-specific route or practice is
justified.

Verdict: park v4p43; do not admit fresh matched StateM arms from it.

## Backup

Remote source and local backup match exactly:

- regular files: 72
- total bytes: 15,317,956
- deterministic tree SHA256:
  `d2ba7fe994615e476bb2edb04c39c0e7c5ad400afd77b796030ae60f20cdc87f`
