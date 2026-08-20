# StateM

<div align="center">

**A command-line state machine for reliable, long-running AI agents.**

[![Project Page](https://img.shields.io/badge/Project-Page-4c6ef5)](https://henryqin1997.github.io/statem/)
[![Paper](https://img.shields.io/badge/Paper-PDF-b31b1b)](https://henryqin1997.github.io/statem/statem-paper.pdf)
[![Hugging Face Papers](https://img.shields.io/badge/Hugging%20Face-Paper-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/papers/2608.15089)
[![X / Twitter](https://img.shields.io/badge/X-Announcement-000000?logo=x&logoColor=white)](https://x.com/henryqin1997/status/2089608567418691863)
[![Version](https://img.shields.io/badge/version-0.1.0-2ea44f)](https://github.com/henryqin1997/statem)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.11-3776ab)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
</div>

## News

[**2026-08-18**]🤗 StateM ranked [**#1 on Hugging Face Daily Papers**](https://huggingface.co/papers/date/2026-08-18).

[**2026-08-18**]🔥 We released the DeepSeek-V4-Flash [StateM runbook and reproducibility release](https://github.com/henryqin1997/statem/releases/tag/deepseek-policy9-tb21-artifacts-20260818), reaching **88.8% descriptive accuracy** on Terminal-Bench 2.1 (395/445 trials; 88.76% unrounded). Everyone can try!

<div align="center">
[![StateM demo](https://henryqin1997.github.io/media/statem/statem-demo-poster-v2.jpg)](https://henryqin1997.github.io/media/statem/statem-demo.mp4)

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

### Edge fields

| Field | Purpose |
| --- | --- |
| `from` / `to` | Source and target nodes |
| `condition` | Transition-specific blocking gate |
| `hook` | Prepare-transfer work after exit gates pass |
| `max_attempts` | Optional positive retry ceiling for this edge and source-node entry |

Leaving out `max_attempts` preserves the default unbounded retry behavior. When
configured, each real `goto` consumes one attempt; blocked checks count, and a
fresh source-node entry receives a fresh budget.

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
| `statem validate SPEC --strict` | Also reject unknown or misplaced runbook keywords |
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

## Till-finish mode (optional)

StateM works without a host hook. To keep an agent moving after it would
otherwise end its turn, register the optional `Stop` hook as a till-finish
mode. When an active run is still on a non-terminal node with outgoing
transitions, the hook returns a continuation prompt that tells the agent to
inspect StateM and continue from the durable state.

1. Start the run normally with `statem start`.
2. For Codex, merge [`codex-stop-autoloop.hooks.json`](examples/hooks/codex-stop-autoloop.hooks.json) into `.codex/hooks.json` or `~/.codex/hooks.json`.
3. For Claude Code, merge [`claude-stop-autoloop.settings.json`](examples/hooks/claude-stop-autoloop.settings.json) into a project or user settings file.
4. If the hook runs outside this repository, replace its command with the absolute path to `integrations/hooks/statem_stop_hook.py`. Set `STATEM_STATE_DIR` too when the run does not use the default `.statem/` directory.

The hook does not advance StateM by itself, bypass transition checks, run
`/clear`, or run `/compact`. It allows the host to stop when no active run
exists, the current state is terminal, or the graph has no outgoing
transition. See the [complete setup and behavior reference](examples/hooks/README.md).

## Integrations

| Host / environment | Entry point |
| --- | --- |
| Codex | [`plugins/statem/skills/statem/SKILL.md`](plugins/statem/skills/statem/SKILL.md) |
| Claude Code | [`integrations/claude/statem/`](integrations/claude/statem/) |
| Harbor / Terminal-Bench | [Executable `git_webserver_deploy` family guide](examples/terminal-bench-2.1-git-webserver-deploy-family.md) |
| Till-finish Stop hook | [`examples/hooks/README.md`](examples/hooks/README.md) |

StateM's core remains host-agnostic: any agent that can run shell commands can query and advance a runbook.

## Examples

| Example | What it demonstrates |
| --- | --- |
| [`coding-agent.yaml`](examples/coding-agent.yaml) | Plan, execute, review, context refresh, and handoff |
| [`git_webserver_deploy` family](examples/terminal-bench-2.1-git-webserver-deploy-family.yaml) · [reproduction guide](examples/terminal-bench-2.1-git-webserver-deploy-family.md) | Executable single-family graph, task-visible routing, fixed end-to-end gate, and Harbor adapters |
| [DeepSeek server-readiness policy extract](examples/terminal-bench-2.1-deepseek-server-readiness-subset.yaml) · [guide](examples/terminal-bench-2.1-deepseek-server-readiness-subset.md) | Auditable, non-executable policy boundary and receipt schema |

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

### DeepSeek policy-v9 artifacts

The [policy-v9 artifact release](https://github.com/henryqin1997/statem/releases/tag/deepseek-policy9-tb21-artifacts-20260818) provides:

- the [exact 54-file task-injected source snapshot](https://github.com/henryqin1997/statem/releases/download/deepseek-policy9-tb21-artifacts-20260818/statem-deepseek-v4-flash-policy9-tb21-source-exact-20260818.tar.gz), verified against the manifest stored with every trial;
- a [runnable reproduction kit](https://github.com/henryqin1997/statem/releases/download/deepseek-policy9-tb21-artifacts-20260818/statem-deepseek-v4-flash-policy9-tb21-reproduction-kit-20260818.tar.gz) with the host-side bridge, frozen control plane, credential-free provider template, and Harbor dry-run guide;
- the [redacted 440-trial result artifact](https://github.com/henryqin1997/statem/releases/download/deepseek-policy9-tb21-artifacts-20260818/statem-deepseek-v4-flash-0731-policy9-88task-k5-public-redacted-20260813.tar.gz), including ATIF trajectories and StateM states, routes, checks, and receipts; and
- [SHA-256 checksums](https://github.com/henryqin1997/statem/releases/download/deepseek-policy9-tb21-artifacts-20260818/SHA256SUMS) for all three archives.

The result artifact covers 88 tasks and excludes `gpt2-codegolf`: it records 392/440 raw passes (89.09%). The table above uses the paper's standard 89-task denominator, 392/445 (88.09%). These large artifacts are hosted as release assets and are not downloaded when cloning or installing StateM.

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
@misc{qin2026statemreaching953raw,
  title         = {StateM: Reaching 95.3\% Raw Accuracy, or a \$15 Frontier Run,
                   on Terminal-Bench 2.1 via Harness Scaling},
  author        = {Ziheng Qin and Yaxin Lu and Zhangyang Atlas Wang and Kai Wang},
  year          = {2026},
  eprint        = {2608.15089},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2608.15089}
}
```
## Acknowledge
We thank Zekai Li and Mengxuan Wu for discussions and feedback on this work.
## License

StateM is released under the [Apache License 2.0](LICENSE).
