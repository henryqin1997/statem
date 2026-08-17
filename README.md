# StateM

<div align="center">

**A command-line state machine for reliable, long-running AI agents.**

[![Project Page](https://img.shields.io/badge/Project-Page-4c6ef5)](https://henryqin1997.github.io/statem/)
[![Paper](https://img.shields.io/badge/Paper-PDF-b31b1b)](https://henryqin1997.github.io/statem/statem-paper.pdf)
[![Version](https://img.shields.io/badge/version-0.1.0-2ea44f)](https://github.com/henryqin1997/statem)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.11-3776ab)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

[![StateM demo](https://henryqin1997.github.io/media/statem/statem-demo-poster.jpg)](https://henryqin1997.github.io/media/statem/statem-demo.mp4)

[Watch or download the 40-second demo](https://henryqin1997.github.io/media/statem/statem-demo.mp4)

</div>

StateM turns an agent workflow into an inspectable graph of states, transitions, and executable checks. It keeps planning, execution, verification, repair, and handoff from collapsing into one long prompt.

## Overview

Long agent runs often fail for ordinary reasons: the original goal fades from attention, progress lives only in chat history, verification is postponed, or a new session cannot reconstruct what happened. StateM moves that procedural state out of the model context and into a lightweight, versioned runbook.

```text
prepare -> execute -> verify -> handoff
              ^          |
              +-- repair-+
```

At every state, the agent can ask:

- What should I do now?
- Which transitions are legal?
- What evidence is required before I move?
- What happened earlier in this run?

The answer is stored in files and runtime history rather than relying on the model to remember everything.

## Why StateM?

| Approach | Remembers phase | Blocks invalid transitions | Supports repair loops | Survives context refresh | Agent-editable |
| --- | :---: | :---: | :---: | :---: | :---: |
| Prompt-only workflow | Partial | No | Informal | No | Yes |
| TODO list | Partial | No | Informal | Yes | Yes |
| CI pipeline | Yes | Yes | Limited | Yes | Usually no |
| General workflow engine | Yes | Yes | Yes | Yes | Rarely |
| **StateM** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

StateM is deliberately smaller than a workflow engine. It is a state-aware runbook that an agent can read, author, inspect, and repair from the command line.

## Highlights

- **Explicit phase boundaries** — model planning, implementation, review, recovery, and handoff as real states.
- **Executable transition gates** — use checklists, commands, predicates, manual approval, and LLM review before leaving a state.
- **Dynamic checks** — let an agent register task-specific checks for the current state entry without mutating the shared runbook.
- **Durable runtime history** — persist the current node, transitions, hook results, evidence, timestamps, and spec identity.
- **Context lifecycle support** — generate safe resume and compaction prompts for long cyclic runs.
- **Zero runtime dependencies** — the core package requires only Python 3.11 or newer.

## Installation

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/henryqin1997/statem.git
cd statem
python3 -m pip install -e .
```

Check the CLI:

```bash
statem --help
```

## Quick start

Validate and start the included coding-agent runbook:

```bash
statem validate examples/coding-agent.yaml
statem start examples/coding-agent.yaml --run-id demo
statem cur --run-id demo
statem next --run-id demo
```

Move only when the current state's checks pass:

```bash
statem goto plan --run-id demo
statem history --run-id demo
```

Runtime data defaults to `.statem/`. For durable machine-local state that survives disposable checkouts, place it outside the repository:

```bash
export STATEM_STATE_DIR="$HOME/.local/state/statem/my-project"
statem start examples/coding-agent.yaml --run-id demo
```

## A minimal runbook

```yaml
name: implementation-loop
initial: plan

nodes:
  plan:
    prompt: |
      Read the task and write a concrete implementation plan.
    before_transfer:
      type: checklist
      items:
        - Scope and constraints are recorded
        - Verification steps are defined

  execute:
    prompt: |
      Implement the plan and keep the change scoped.
    before_transfer:
      - type: command
        run: "python3 -m pytest -q"
      - type: checklist
        items:
          - Relevant tests pass
          - Unrelated files were not changed

  handoff:
    prompt: |
      Summarize the change, verification, and remaining risks.

edges:
  - from: plan
    to: execute
    condition: The plan is ready.
  - from: execute
    to: plan
    condition: Verification found a fixable gap.
  - from: execute
    to: handoff
    condition: The implementation and verification are complete.
```

Save it as `runbook.yaml`, then run:

```bash
statem validate runbook.yaml
statem start runbook.yaml --run-id my-run
statem cur --run-id my-run
```

## How it works

StateM separates the shared workflow definition from per-run execution state:

| Layer | Contents | Commit to git? |
| --- | --- | --- |
| Static runbook | Nodes, edges, prompts, hooks, gates | Yes |
| Runtime state | Current node, history, results, timestamps | No |
| Dynamic checks | Task-specific current-entry verification | No |
| Durable project notes | Plans, decisions, progress, artifacts | Usually yes |

A transition is a transaction:

1. Resolve the requested outgoing edge.
2. Run the current node's `before_transfer` checks.
3. Load and run current-entry dynamic checks.
4. Evaluate the edge's `condition`.
5. Run the current node's `out_hook` and the edge `hook`.
6. Record the transition, create a new target entry, and run the target node's `in_hook`.

If a blocking check fails, the agent remains in the current state with the failure recorded for repair.

## Runbook reference

### Top-level fields

| Field | Purpose |
| --- | --- |
| `name` | Human-readable graph name |
| `initial` | Node entered when a new run starts |
| `nodes` | Named state definitions |
| `edges` | Directed transitions between states |

### Node fields

| Field | When it runs | Typical use |
| --- | --- | --- |
| `prompt` / `pre_request` | While the node is active | State-local instructions |
| `in_hook` | After entering | Load context or initialize evidence |
| `before_transfer` | Before leaving | Block on required verification |
| `dynamic_before_transfer` | Before leaving | Run task-specific current-entry checks |
| `out_hook` | Before the transition commits | Persist progress or handoff notes |

### Check and hook types

| Type | Behavior |
| --- | --- |
| `message` | Display non-blocking guidance |
| `manual` | Ask for explicit confirmation |
| `checklist` | Confirm a set of completion conditions |
| `command` | Run a shell command and use its exit code |
| `predicate` | Inspect files declaratively |
| `llm_review` | Delegate a structured review to an external command/model |

Checks can be configured with fields such as `blocking`, `on_failure`, `timeout`, and `cwd`. Prefer checks that exercise the same interface the task promises to its eventual consumer.

## CLI at a glance

| Command | Purpose |
| --- | --- |
| `statem start SPEC` | Create or resume a run |
| `statem cur` | Show the current node and its prompt |
| `statem state` | Show the full graph |
| `statem ls NODE` | Inspect one node |
| `statem next` | Show outgoing transitions |
| `statem goto TARGET` | Attempt a checked transition |
| `statem save` | Persist state and run the current `out_hook` |
| `statem history` | Inspect prior transitions and results |
| `statem prompt` | Generate a durable post-clear resume prompt |
| `statem compact-prompt` | Generate a safe compaction prompt |
| `statem validate SPEC` | Validate graph structure and references |
| `statem dynamic ...` | Manage current-entry dynamic checks |

Most commands accept `--run-id`, `--state-dir`, and `--json` for explicit run selection, isolated state, and machine-readable output.

## Dynamic checks

Static gates cover invariants known when the runbook is authored. Dynamic checks cover verification discovered during the concrete task—for example, a regression test for the exact bug just fixed.

```bash
statem dynamic path --run-id demo
statem dynamic write checks.json --run-id demo --agent-id implementer
statem dynamic list --run-id demo --json
```

Dynamic checks are scoped to the current node entry. StateM records who registered them and runs them before the transition is allowed to commit.

## Context and recovery

Long runs should keep durable facts in project files and use the model context for the current decision. StateM supports that split with:

- `statem history` for the durable transition record;
- `statem prompt` for restoring attention after a cleared session;
- `statem compact-prompt` for safe compaction inside cyclic runbooks;
- explicit recovery or session-refresh nodes when another loop should continue;
- spec hashes and run identifiers to detect or deliberately rebind edited runbooks.

Runbooks belong in version control. Runtime state does not. Add `.statem/` to `.gitignore` when using the default local state directory.

## Integrations

| Host / environment | Entry point |
| --- | --- |
| Codex | [`plugins/statem/skills/statem/SKILL.md`](plugins/statem/skills/statem/SKILL.md) |
| Claude Code | [`integrations/claude/statem/`](integrations/claude/statem/) |
| Stop-hook auto loop | [`examples/hooks/README.md`](examples/hooks/README.md) |

StateM's core remains host-agnostic: any agent that can run shell commands can query and advance a runbook.

## Examples

| Example | What it demonstrates |
| --- | --- |
| [`coding-agent.yaml`](examples/coding-agent.yaml) | Plan, execute, review, context refresh, and handoff |

For advanced guidance on evidence receipts, consumer-facing checks, adaptive verifier plans, freshness, recovery, and benchmark integrity, read the [verification guide](docs/verification-guide.md).

## Evaluation snapshot

The accompanying paper evaluates StateM as an execution harness on Terminal-Bench 2.1. These are system-level results, not claims about a new base model:

| Configuration | Result | Operating condition |
| --- | ---: | --- |
| GPT-5.5 xhigh + StateM | 92.1% | 89 tasks, 445 trials; 88/89 five-trial coverage |
| GPT-5.6 Sol xhigh + frozen StateM profile | 95.28% raw | 424/445 public-submission trials; 89/89 coverage |
| DeepSeek-V4-Flash + adapted StateM profile | 88.09% | 392/445 under standard timeouts |
| DeepSeek-V4-Flash + adapted StateM profile | 88.76% descriptive | 395/445, replacing one task with disclosed extended-timeout trials |

The 95.28% value is the raw pre-adjudication public-submission score. The DeepSeek descriptive aggregate is reported separately from the standard-timeout result. See the [paper](https://henryqin1997.github.io/statem/statem-paper.pdf) for experimental protocol, references, costs, and limitations.

## Project layout

```text
statem/                  Core state machine and CLI
examples/                Runbooks and hook examples
integrations/            Host adapters
plugins/statem/          Codex skill packaging
tests/                   Unit and integration tests
design.md                Detailed runtime and schema design
docs/verification-guide.md
                        Advanced verification patterns
```

README media is served from the separate `henryqin1997.github.io` repository, so cloning or installing StateM does not download the demo video.

## Where to go next

1. Start with [`examples/coding-agent.yaml`](examples/coding-agent.yaml) and remove any states your workflow does not need.
2. Read [`design.md`](design.md) when you need the full runtime, transition, hook, and recovery semantics.
3. Add deterministic `before_transfer` checks at consequential boundaries.
4. Use dynamic checks only when the concrete task reveals a verification need the shared runbook could not know in advance.
5. Keep large outputs and durable decisions in files; keep the active model context focused on the current state.

## Citation

```bibtex
@article{qin2026statem,
  title  = {StateM: Reaching 95.3\% Raw Accuracy, or a \$15 Frontier Run,
            on Terminal-Bench 2.1 via Harness Scaling},
  author = {Qin, Ziheng and Lu, Yaxin and Wang, Zhangyang and Wang, Kai},
  year   = {2026}
}
```

## License

StateM is released under the [Apache License 2.0](LICENSE).
