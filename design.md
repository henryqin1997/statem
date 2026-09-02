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

Runtime state is separate from the static spec. It defaults to `.statem/`, but
can live in a machine-local directory selected with `STATEM_STATE_DIR` or
`--state-dir`.

- run id
- spec path and spec hash
- current state pointer and current node entry id
- transition history
- hook and condition results
- dynamic check manifests and current-entry check files
- timestamps

This separation makes graph edits safer and lets each agent have its own run.
YAML runbooks should be committed with the repo as shared process definitions.
Runtime state should not be committed; it is local, copy-on-use execution data
for one machine, agent, and run id.
For dynamic servers or company machines where git checkouts may be deleted,
runtime state should live outside the repo, such as
`$HOME/.local/state/statem/<project>`, so it can persist across checkouts.
After moving to a new checkout, `statem start SPEC --run-id ID` should be run
once to rebind the run to the current spec path.

### Node

A node has:

- `name`
- `prompt` or `pre_request`: instructions for the agent while in the node
- optional `in_hook`
- optional `before_transfer`
- optional `dynamic_before_transfer`
- optional `out_hook`

`in_hook` is for setup after entering a node: load durable context, remind the
agent what to read, initialize files, or prepare node-local state.
`before_transfer` runs while still in the current node and is the right place
for shared redo/check loops authored in the static runbook.
`dynamic_before_transfer` is a state-level exit gate for checks generated after
the agent has inspected the actual task, code, implementation approach, or
component memory for this node entry.
`out_hook` persists progress before leaving the node.

### Dynamic Before Transfer

Static `before_transfer` is best for checks that are known when the runbook is
authored. Some checks are task-specific: after reading the current task and
implementation details, the agent may need to write a custom checklist or file
predicate that did not exist in the original YAML. Nodes can declare
`dynamic_before_transfer` for this case.

Version 1 supports `path: current_entry`. Each time a run enters a node,
`statem` creates a new entry id and a dynamic check directory under runtime
state:

```text
.statem/runs/<run-id>/nodes/<node>/<entry-id>/dynamic_before_transfer/
  manifest.json
  checks.<agent-id>.json
```

Agents should use the CLI instead of hand-building paths:

```bash
statem dynamic path --run-id ID --json
statem dynamic write checks.json --run-id ID --agent-id agent-a --json
statem dynamic list --run-id ID --json
```

The node `in_hook` is a good place to remind the agent to generate or refresh
these dynamic checks. `dynamic_before_transfer` is not setup; it is the gate
that loads and runs the current-entry checks during `goto`.

Supported dynamic check items use the same typed check model as static hooks:
`manual`, `message`, `checklist`, `command`, `predicate`, and `llm_review`.
Node config can constrain them with fields such as `required`, `min_items`,
`require_reason`, `require_basis`, `allow_types`, and
`stale_policy: require_confirmation`. Missing required files, disallowed check
types, invalid payload shape, or failing check results block the transition.

On every `goto` attempt, `statem` reloads the latest dynamic checks for the
current entry and records a snapshot in history. If the dynamic gate fails, the
run stays on the same node with the same entry id so the agent can revise the
implementation or rewrite its dynamic check file and retry. A successful
transition creates a fresh entry id for the target node.

### Edge

An edge may set `max_attempts` to a positive integer. The limit is scoped to the
source node's current entry and counts every real `goto` attempt, including
attempts blocked by a gate. Omitting the field keeps retries unbounded for
backward compatibility.

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
3. Load and run current node `dynamic_before_transfer`, if configured.
4. Run edge `condition`.
5. If a blocking pre-leave gate fails, stay in the current node with the same
   entry id and log the attempt.
6. Run current node `out_hook`.
7. Run edge `hook` as prepare-transfer work.
8. If a blocking `out_hook` or edge `hook` fails, stay in the source node and
   log the attempt.
9. Persist `current = TARGET` and create the target node entry id.
10. Run target node `in_hook`.
11. Record transition history.

This gives agents a clean chance to redo work before leaving the node.

Hook role summary:

- `in_hook`: setup for the node that has just been entered.
- `before_transfer`: checks/redos while still in the current node.
- `dynamic_before_transfer`: current-entry checks generated from the concrete
  task or implementation state.
- edge `condition`: transition-specific gate after node-level exit checks.
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

These types are shared by static node hooks, edge conditions/hooks, and dynamic
current-entry checks. The purpose controls defaults: conditions,
`before_transfer`, and `dynamic_before_transfer` are gating by default. Plain
setup/reminder hooks are normally non-blocking unless explicitly marked
blocking.

Every hook/check should have robust defaults:

- `blocking`: defaults to true for gating purposes and for explicit checks,
  false for plain setup/reminder messages.
- `on_failure`: defaults to `block` for blocking checks, `continue` for
  non-blocking reminders.
- `timeout`: optional for command hooks.
- `cwd`: optional command working directory.

### Non-Interactive Execution

`statem` is designed to be driven by agents, which are often non-interactive
(stdin is not a terminal, or no input is ever provided). Behavior in these
environments:

- `manual` and `checklist` items require explicit confirmation. When stdin is
  not a TTY, they fail the check with a message telling the caller to rerun
  with `--yes` instead of reading stdin.
- If stdin is a TTY but the input stream ends before an answer is given (EOF),
  the check fails gracefully and tells the caller to rerun with `--yes` rather
  than raising a traceback.
- `--yes` auto-confirms every `manual` and `checklist` item. It does not bypass
  `predicate`, `command`, or `llm_review` checks.
- Exit codes are machine-usable: `0` means the transition committed, `2` means
  a gate blocked and the run stayed in its source node, and `1` is reserved for
  invalid input or an operational error.

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

Relative predicate `path` values and relative command `cwd` values resolve
against the directory containing the runbook spec (`spec.path.parent`), not the
caller's current working directory. Absolute paths are used as-is. This keeps
checks stable when a run starts from another directory or moves to a new
checkout.

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
- `statem history [--tail N] [--json]`: show run history.
- `statem dynamic path [--json]`: show the current-entry dynamic check
  directory.
- `statem dynamic write CHECKS_FILE [--agent-id ID] [--agent-role ROLE]`:
  normalize and register one agent's dynamic checks for the current entry.
- `statem dynamic list [--json]`: show registered current-entry dynamic check
  producers and files.
- `statem prompt [--json]`: print a durable post-`/clear` resume prompt.
- `statem compact-prompt [--json]`: print a safe `/compact` prompt for cyclic
  runbooks.
- `statem validate SPEC`: validate graph shape and references.
- `statem validate SPEC --strict`: also reject unknown or misplaced keywords
  throughout the supported runbook schema.

`before_transfer` is not a CLI command. It is a node spec field shown by
`statem cur`/`statem ls` and executed automatically by `statem goto` before the
current node is allowed to exit.
`dynamic_before_transfer` is also a node spec field, but agents manage its
current-entry check files with `statem dynamic path`, `statem dynamic write`,
and `statem dynamic list`.

When a JSON transition fails, the error payload should include structured
details about the failed check or hook, including `stage` and `results`, so
agents can recover without rerunning a non-JSON command just to inspect the
failure.

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
The generated prompt should pin the current run id and explicitly tell the host
to ignore older statem run ids or stale commands from prior chat context.

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

## Feedback Backlog

Early agent feedback suggests these v2 directions:

- Evidence cache: allow a command or verification hook to reuse recent passing
  evidence within a configurable time window, while still making fresh checks
  the safe default.
- Run variables: store small first-class run fields such as
  `selected_issue=q_quant-y7a` outside chat context and expose them in hooks,
  prompts, and JSON output.
- History summary: add a compact handoff-oriented view over recent events beyond
  `history --tail N`.
- Integration modes: for tools such as Beads, support sandbox-friendly
  export-only behavior that avoids noisy git staging attempts.

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
  in_hook: ask agent to write task-specific dynamic exit checks when needed
  before_transfer: review shared implementation checklist
  dynamic_before_transfer: run current-entry checks generated from the task
  out_hook: update progress.md
  goto review

review
  before_transfer: check implementation, constraints, verification, risks
  goto session_refresh when another loop is needed and context is noisy

session_refresh
  prompt: run statem compact-prompt, compact safely, restore with cur/history
  goto plan
```
