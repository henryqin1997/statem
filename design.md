# Command Line State Machine

## Motivation

Agents can get messed up or fail to follow instructions in long execution
cycles when the whole process is configured only by prompts. Recent context gets
more attention, older instructions get diluted, and the agent has to carry too
much procedural state in its own context window.

Visual graph tools are not natural enough for agents to operate directly, while
large orchestration frameworks are often too heavy to configure, test, and
repair during a real engineering loop. `statem` is a command line state machine
that maps an execution graph into a simple agent-readable runbook. Agents query
the current state, inspect allowed next states, and move with explicit checks.

The intent is not to build a hard harness like a workflow engine. The intent is
to give agents a state-aware runbook with enough structure to prevent drift,
support redo loops, preserve progress, and resume long runs.

Notes:

- Use the file system as external memory by default.
- Keep the core light enough for agents to author their own specs.
- Coding-agent hooks are useful, but they are not state-aware enough by
  themselves.

## Design

`statem` is an interactive graph with automatic IO around transitions. Most IO
is text intended for the agent, but hooks and conditions can also run shell
commands or typed file predicates. Natural language should be the default setup
path because it is the easiest thing for agents to generate from a diagram or
hand-drawn process.

## Abstraction

### Static Spec

The static spec lives in a user-authored YAML-like file.

- `name`: graph name.
- `initial`: starting node.
- `nodes`: node definitions.
- `edges`: directed transitions.

### Runtime State

Runtime state is separate from the static spec. It lives under `.statem/`.

- run id
- spec path and spec hash
- current state pointer
- transition history
- hook and condition results
- timestamps

This separation makes graph edits safer and lets each agent have its own run.

### Node

A node has:

- `name`
- `prompt` or `pre_request`: instructions for the agent while in the node
- optional `in_hook`
- optional `before_transfer`
- optional `out_hook`

`in_hook` is for setup after entering a node: load durable context, remind the
agent what to read, initialize files, or prepare node-local state.
`before_transfer` runs while still in the current node and is the right place
for redo/check loops.
`out_hook` persists progress before leaving the node.

### Edge

An edge has:

- `from`
- `to`
- optional `condition`
- optional `hook`

The condition decides whether the transition is allowed. The edge `hook` is a
prepare-transfer hook: it runs after the current node's `out_hook` and before
the new node is entered. If a blocking edge hook fails, the current pointer stays
at the source node so the agent can retry.

## Transition Transaction

`statem goto TARGET` is the primary transition command. `transfer` can exist as
a compatibility alias, but `goto` is more natural for agents.

Transition order:

1. Resolve current node and target edge.
2. Run current node `before_transfer` checks.
3. Run edge `condition`.
4. If a blocking check fails, stay in the current node and log the attempt.
5. Run current node `out_hook`.
6. Run edge `hook` as prepare-transfer work.
7. If a blocking `out_hook` or edge `hook` fails, stay in the source node and
   log the attempt.
8. Persist `current = TARGET`.
9. Run target node `in_hook`.
10. Record transition history.

This gives agents a clean chance to redo work before leaving the node.

Hook role summary:

- `in_hook`: setup for the node that has just been entered.
- `before_transfer`: checks/redos while still in the current node.
- `out_hook`: persist current-node progress before leaving.
- edge `hook`: prepare the transfer after persistence and before entering the
  target node.

## Conditions And Hooks

Natural language is the default. A string condition or hook is treated as a
manual agent check: show the instruction and ask for yes/no confirmation.

Typed conditions and hooks should also be supported:

- `manual`: show text and ask the agent to confirm yes/no.
- `message`: show text only; usually non-blocking.
- `command`: run a shell command and use its exit code.
- `checklist`: ask the agent to confirm multiple items.
- `predicate`: declaratively inspect files without shell commands.
- `llm_review`: call an external reviewer command/model and use its result.

Every hook/check should have robust defaults:

- `blocking`: defaults to true for conditions, false for message hooks.
- `on_failure`: defaults to `block` for blocking checks, `continue` for
  non-blocking reminders.
- `timeout`: optional for command hooks.
- `cwd`: optional command working directory.

### Typed File Predicate

A typed predicate is a declarative file check, not a shell command. It lets the
spec say what must be true about external memory in a portable, structured way.

Examples:

```yaml
condition:
  type: predicate
  path: progress.md
  exists: true
  non_empty: true
```

```yaml
condition:
  type: predicate
  path: .statem/checks.json
  json_path: plan.reviewed
  equals: true
```

This is safer and easier to inspect than embedding shell for common checks.

### LLM Review

`llm_review` is intentionally generic. The spec can provide a command in `run`,
or the environment can provide `STATEM_LLM_REVIEW_CMD`. `statem` sends the
review prompt on stdin and treats a zero exit code as success. Specs can also
require output markers such as `accept_contains` or `accept_regex`.

Example:

```yaml
condition:
  type: llm_review
  prompt: "Review whether the implementation is ready to leave execute."
  run: "codex exec --ask-for-approval never"
  accept_contains: "APPROVED"
  timeout: 120
```

## CLI API

Agent-readable output should be the default. JSON output should be available
for every command that agents may parse.

Commands:

- `statem start SPEC [--run-id ID]`: create or resume a run from a spec.
- `statem cur [--json]`: show current node, prompt, and outgoing transitions.
- `statem state [--json]`: list the full runbook graph, including all states
  and edges.
- `statem ls NODE [--json]`: show node details.
- `statem next [--json]`: show allowed next states from current node.
- `statem goto TARGET`: move to a next state using the transition transaction.
- `statem transfer TARGET`: alias for `goto`.
- `statem save`: persist runtime state and run the current node `out_hook`.
- `statem history [--json]`: show run history.
- `statem prompt [--json]`: print a durable post-`/clear` resume prompt.
- `statem compact-prompt [--json]`: print a safe `/compact` prompt for cyclic
  runbooks.
- `statem validate SPEC`: validate graph shape and references.

`before_transfer` is not a CLI command. It is a node spec field shown by
`statem cur`/`statem ls` and executed automatically by `statem goto` before the
current node is allowed to exit.

## Context Clear

Avoiding `/clear` in normal loops is a careful design choice. `/clear` is
outside the state machine and flushes the conversation, including any
instructions that were supposed to run after it. It also can erase useful user
intent or recent reasoning that was not written to durable files yet. `statem`
should prefer explicit state transitions plus safe compaction over hard
clearing.

If a hard clear is truly needed, run `statem prompt --run-id ID` first and paste
the generated prompt immediately after `/clear`. That prompt tells the next
agent context to recover from `.statem` by running `start`, `cur`, and
`history`.

## Session Hygiene Nodes

For loop-based runbooks, model context cleanup as an explicit node in the graph.
The node should appear after a full loop has completed and only when another
cycle will continue. It should not be hidden inside every transition.

The preferred cleanup action is safe compaction, not hard clearing. Use
`statem compact-prompt --run-id ID` to generate a `/compact` instruction that
keeps durable state and discards stale failed attempts, noisy tool output,
superseded plans, and irrelevant conversation. After compaction, the agent
should immediately run `statem cur` and `statem history` to restore attention to
the current node.

Agents may inspect the full runbook with `statem state`; the graph is not meant
to be hidden. `cur`, `next`, and `goto` are for disciplined execution and
attention anchoring, while compaction removes conversation that is no longer
needed as state executor context.

This keeps loop state explicit while reducing attention pollution from earlier
attempts. Actual slash-command execution remains a host/user action; `statem`
core only produces the instruction packet.

## Host Stop Hook Auto Loop

Some hosts can run a `Stop` hook when the agent is about to hand control back
to the user. `statem` can use that as an opt-in auto-loop guard: if there is an
active run and the current node still has outgoing transitions, the hook returns
a continuation prompt telling the agent to inspect `statem cur`, inspect
`statem next`, follow the current node prompt, and move only with
`statem goto`.

This is intentionally host glue, not core state-machine behavior:

- The Stop hook does not advance the graph.
- The Stop hook does not send slash commands such as `/clear` or `/compact`.
- The Stop hook allows stopping when the current node is a handoff/done state
  or has no next transitions.
- The Stop hook must check the host recursion guard, such as
  `stop_hook_active`, so one continuation does not become an infinite loop.

The repository includes `integrations/hooks/statem_stop_hook.py` and example
registration snippets:

- `examples/hooks/README.md`
- `examples/hooks/codex-stop-autoloop.hooks.json`
- `examples/hooks/claude-stop-autoloop.settings.json`

Register by merging the matching snippet into the host hook configuration and
using an absolute script path if the hook is registered outside the `statem`
repository.

The default stop states are `handoff`, `done`, `complete`, `completed`, and
`finished`. Override them with `STATEM_AUTOLOOP_STOP_STATES` when a runbook uses
different terminal node names. Override the statem command with
`STATEM_COMMAND` when `statem` is installed somewhere other than the current
Python environment.

This can replace prompt-only "keep working" loops with explicit state control:
the host only re-enters the model, while `statem` remains the source of truth
for current state, allowed next states, hooks, and history.

## Graph Edits During A Run

Editing the spec and restarting should be possible, but must be explicit:

- `statem validate SPEC` checks graph structure.
- `statem start SPEC --run-id ID` resumes an existing run if the current node
  still exists and reruns that node's `in_hook`.
- If the current node was removed or renamed, startup moves the pointer to
  `initial`, logs a `migrate_current` event, and runs the initial node's
  `in_hook`.

## Example Coding Agent Loop

```text
start
  in_hook: remind agent to load durable task setup
  before_transfer: confirm necessary files were read
  goto plan

plan
  prompt: load task context, current progress, architecture.md, generate plan
  before_transfer: check plan reviewed and golden rules considered
  goto execute

execute
  prompt: load context, progress, architecture.md, golden rules, plan, execute
  before_transfer: review implementation against checklist
  out_hook: update progress.md
  goto review

review
  before_transfer: check implementation, constraints, verification, risks
  goto session_refresh when another loop is needed and context is noisy

session_refresh
  prompt: run statem compact-prompt, compact safely, restore with cur/history
  goto plan
```
