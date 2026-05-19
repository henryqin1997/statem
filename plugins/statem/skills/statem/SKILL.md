---
name: statem
description: Use when a long coding or research task should be managed with statem state-machine runbooks, including creating specs, starting or resuming runs, checking current state, transitioning with goto, saving progress, and reading history.
---

# Statem

Use `statem` when the task is long-running, iterative, easy to lose track of, or benefits from explicit agent state. Prefer it as a runbook, not as a rigid harness.

## Workflow

1. Find or create a statem spec such as `statem.yaml`.
2. Validate it: `python3 -m statem validate statem.yaml --json`.
3. Start or resume a run: `python3 -m statem start statem.yaml --run-id <id> --json`.
4. Check state before acting: `python3 -m statem cur --run-id <id> --json`.
5. Move only through allowed edges: `python3 -m statem goto <node> --run-id <id> --json`.
6. Save progress before pausing: `python3 -m statem save --run-id <id> --json`.

Use `statem` instead of `python3 -m statem` if the CLI is installed on PATH.

## Context Clear

Avoid `/clear` in normal loops. It flushes the conversation, including any
instructions that were supposed to run after it, and can lose useful intent that
was not written to durable files. Prefer explicit transitions plus safe
compaction.

Before a hard clear, generate a durable resume prompt:

```bash
python3 -m statem prompt --run-id <id>
```

Paste the generated prompt immediately after `/clear`. The agent must recover
from `.statem` with `start`, `cur`, and `history`; it should not rely on any
pre-clear conversation.

## Loop Compaction

For cyclic runbooks, prefer an explicit session hygiene node after a full loop.
When continuing another cycle and context is noisy, generate a safe compaction
instruction:

```bash
python3 -m statem compact-prompt --run-id <id>
```

Run the generated `/compact` instruction through the host UI, then recover with
`statem cur` and `statem history`. Do not use hidden self-messaging to trigger
compaction.

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

## Authoring Specs

- Keep the static spec separate from `.statem/` runtime state.
- Use natural-language checks for low-friction runbooks.
- Use `in_hook` for setup after entering a node.
- Use `before_transfer` for redo/check loops while still in the current node.
  It is a spec field, not a CLI command; `statem goto` runs it automatically.
- Use `out_hook` to persist current-node progress before leaving.
- Use edge `hook` as prepare-transfer work after `out_hook` and before entering
  the target. If a blocking edge hook fails, the pointer stays at the source so
  the agent can retry.
- Use `type: command` for deterministic shell checks.
- Use `type: predicate` for file existence, non-empty files, text matches, and JSON-path checks.
- Use `type: llm_review` when another model, agent, or script should review before a transition.

Do not manually edit `.statem/runs/<run-id>/state.json` unless the user explicitly asks for runtime surgery.
