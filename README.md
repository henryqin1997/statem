# statem

`statem` is a command line state machine for agent long runs. It turns an
execution graph into an agent-readable runbook: the agent can inspect the
current node, see allowed next states, run checks and hooks, save progress, and
resume after context changes.

It is an agent-native runbook, not a hard workflow harness. The goal is to keep
smart agents oriented during long coding, research, and review loops without
forcing every step into a large orchestration framework.

## Why

Prompt-only long runs drift. Recent chat gets too much attention, old
instructions fade, and agents lose track of what was already checked. Heavy
graph orchestration frameworks can also be awkward to author, debug, and repair
inside a live agent session.

`statem` keeps the procedural state outside the model context:

- static graph in a small spec file
- runtime state in `.statem/`
- durable history of transitions, checks, and hooks
- explicit `goto` transitions instead of implicit "keep working" prompts
- optional host Stop hook for auto-loop behavior

## Install

Clone repository:

```bash
git clone https://github.com/henryqin1997/statem.git
cd statem
```

From this repository:

```bash
pip install -e .
```

That installs the `statem` CLI command:

```bash
statem --help
```

You can also run the same CLI without installing, which is useful during local
development:

```bash
python3 -m statem --help
```

All examples below use `statem`. Replace it with `python3 -m statem` if you are
running directly from a checkout without installing.

## Quick Start

Validate the example coding-agent runbook:

```bash
statem validate examples/coding-agent.yaml --json
```

Start a run:

```bash
statem start examples/coding-agent.yaml --run-id demo --json
```

Inspect current state:

```bash
statem cur --run-id demo
statem next --run-id demo
```

Move only through allowed edges:

```bash
statem goto plan --run-id demo
```

Use `--yes` only when you intentionally want to auto-confirm manual checks and
checklists:

```bash
statem goto plan --run-id demo --yes
```

## CLI

Common commands:

- `statem start SPEC [--run-id ID]`: create or resume a run.
- `statem cur [--json]`: show current node, prompt, hooks, and outgoing edges.
- `statem state [--json]`: show the full runbook graph.
- `statem next [--json]`: show allowed next states.
- `statem goto TARGET`: move through a checked transition.
- `statem save`: persist state and run the current node `out_hook`.
- `statem history [--tail N] [--json]`: show transition and hook history.
- `statem prompt`: print a durable post-`/clear` recovery prompt.
- `statem compact-prompt`: print a safe `/compact` prompt for cyclic runbooks.
- `statem validate SPEC`: validate graph shape and references.

`statem transfer TARGET` is kept as an alias for `goto`.

## Spec Fields

Top-level fields:

- `name`: runbook name.
- `initial`: starting node.
- `nodes`: mapping of node names to node definitions.
- `edges`: list of directed transitions.

Node fields:

- `prompt`: instructions for the agent while in this state.
- `in_hook`: setup after entering the node.
- `before_transfer`: checks and redo gates before leaving the node.
- `out_hook`: persistence work before leaving the node.

Edge fields:

- `from`: source node.
- `to`: target node.
- `condition`: gate that decides whether transition is allowed.
- `hook`: prepare-transfer work after `out_hook` and before entering target.

Hook/check types:

- `manual`: ask the agent to confirm yes/no.
- `message`: show an instruction or reminder.
- `checklist`: ask the agent to confirm multiple items.
- `command`: run a shell command; exit code controls success.
- `predicate`: check files or JSON state without shell.
- `llm_review`: call another model, agent, or reviewer command.

## Transition Order

`statem goto TARGET` runs a transaction:

1. Resolve the current node and target edge.
2. Run current node `before_transfer`.
3. Run edge `condition`.
4. If a blocking check fails, stay at the current node.
5. Run current node `out_hook`.
6. Run edge `hook`.
7. If a blocking transfer hook fails, stay at the source node.
8. Persist `current = TARGET`.
9. Run target node `in_hook`.
10. Record history.

This makes retry behavior simple: fix the failed check, then rerun `goto`.
When `--json` is used and a transition is blocked, the error payload includes a
`details.results` list with the failed checklist, command, predicate, or review
output.

## Runtime State

Runtime state is separate from the static spec and lives under `.statem/`.

Each run has its own id and state file, so multiple agents can use the same
runbook without sharing a current pointer. Graph edits are handled on restart:
if the current node still exists, `statem start` resumes it and reruns its
`in_hook`; if the node was removed, it moves to `initial` and logs the
migration.

## Context Hygiene

Avoid `/clear` in normal loops. It flushes the conversation, including any
instruction that was supposed to happen after it. Prefer explicit state
transitions plus safe compaction.

For cyclic runbooks, model context cleanup as a normal node, usually after a
full review pass. Use:

```bash
statem compact-prompt --run-id ID
```

If a hard clear is truly necessary, first generate a recovery prompt:

```bash
statem prompt --run-id ID
```

Paste that generated prompt immediately after `/clear` so the next context can
recover from `.statem`.

For handoffs, use `statem history --tail 10 --json` to keep the recent run
history compact enough for an agent or user to scan.

## Auto Loop Hook

Hosts with Stop hooks can opt into auto-loop behavior. The included adapter
checks the active `.statem` run when the agent is about to hand control back to
the user. If the current node still has outgoing transitions and is not a
terminal handoff node, it asks the host to continue with a prompt that tells the
agent to inspect `statem cur` and keep working from the current state.

Files:

- `integrations/hooks/statem_stop_hook.py`
- `examples/hooks/README.md`
- `examples/hooks/codex-stop-autoloop.hooks.json`
- `examples/hooks/claude-stop-autoloop.settings.json`

The hook does not advance state, run `/clear`, or run `/compact`. It only nudges
the agent back into the explicit runbook.

## Codex And Claude

This repository includes local integration scaffolding:

- Codex plugin skill: `plugins/statem/skills/statem/SKILL.md`
- Claude Code skill/plugin: `integrations/claude/statem/`

These integrations teach the host agent when to use `statem`, how to transition
safely, and how to avoid context-clearing footguns.

## Example

The main example is:

```text
examples/coding-agent.yaml
```

It models a coding loop:

```text
start -> plan -> execute -> review -> handoff
                         \-> execute
                         \-> session_refresh -> plan
```

Use it as a starting template for coding agents that need planning, execution,
review, optional compaction, and explicit handoff.

## Design Notes

See `design.md` for the full rationale, hook semantics, transaction details,
graph migration behavior, and future design considerations.

## License

Apache License 2.0. See `LICENSE`.
