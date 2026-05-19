---
name: use-statem
description: Manage long Claude Code work with statem state-machine runbooks. Use when tasks need durable state, explicit transitions, redo loops, save/resume behavior, or cross-agent review.
argument-hint: [task-or-spec]
allowed-tools: Bash(statem *) Bash(python3 -m statem *)
---

# Use Statem

Use `statem` as a state-aware runbook for long agent runs. It should guide the work and preserve progress without turning the session into a rigid workflow harness.

## Operating Loop

1. Inspect or create a spec such as `statem.yaml`.
2. Run `statem validate statem.yaml --json`.
3. Start or resume with `statem start statem.yaml --run-id <id> --json`.
4. Before work, run `statem cur --run-id <id> --json`.
5. When a state is complete, run `statem goto <next> --run-id <id> --json`.
6. Before pausing, run `statem save --run-id <id> --json`.

If `statem` is not on PATH, use `python3 -m statem` from the repository that contains the Python package.

## Context Clear

Avoid `/clear` in normal loops. It flushes the conversation, including any
instructions that were supposed to run after it, and can lose useful intent that
was not written to durable files. Prefer explicit transitions plus safe
compaction. Before a hard clear, run
`statem prompt --run-id <id>` and paste the generated prompt immediately after
`/clear`. After a hard clear, recover from `.statem` with `start`, `cur`, and
`history` instead of relying on previous chat context.

## Loop Compaction

For cyclic runbooks, prefer an explicit session hygiene node after a full loop.
When another cycle will continue and the context is noisy, run
`statem compact-prompt --run-id <id>`, use the generated `/compact`
instruction, then recover with `statem cur` and `statem history`.

Agents may inspect the full graph with `statem state`; `cur`, `next`, and
`goto` are for disciplined execution and attention anchoring, not for hiding the
runbook.

## Auto Loop Hook

When the host supports a Stop hook, users may opt into auto-loop behavior with
`integrations/hooks/statem_stop_hook.py`. The hook runs when the agent is about
to hand control back to the user. If a statem run is active, the current node is
not a terminal/handoff node, and there are outgoing transitions, it returns a
continuation prompt that tells the agent to inspect `statem cur` and keep
working from the current node.

Registration examples live in:

- `examples/hooks/README.md`
- `examples/hooks/codex-stop-autoloop.hooks.json`
- `examples/hooks/claude-stop-autoloop.settings.json`

Merge the matching snippet into the host hook configuration and use an absolute
script path if the hook is registered outside the statem repository.

Treat this as host-level glue. It must not advance state, run `/clear`, or hide
the graph. The agent should still transition only with `statem goto`.

## Spec Guidance

- Put runtime data under `.statem/`; do not mix it into the spec.
- Use `in_hook` for setup after entering a node.
- Use `before_transfer` for checks/redos while still in the current node.
  It is a spec field, not a CLI command; `statem goto` runs it automatically.
- Use `out_hook` to persist current-node progress before leaving.
- Use edge `hook` as prepare-transfer work after `out_hook` and before entering
  the target. If a blocking edge hook fails, the pointer stays at the source so
  the agent can retry.
- Use `type: command` for deterministic shell checks and hooks.
- Use `type: predicate` for file checks instead of shell when possible.
- Use `type: llm_review` to call Codex, Claude, or another reviewer command.
- Treat blocked transitions as useful feedback: stay in the node, fix the issue, then retry.
