# Construction daily report

This example distills a production document pipeline into a StateM runbook. The
pipeline produces one construction daily report per calendar day for building
sites in Brazil, where the document has legal weight: an LLM proposes the data,
a deterministic fail-closed validator judges it against the real bytes of the
sources, a human signs off, and the accepted day is archived as a verified
golden trajectory.

It was written after a public exchange with the StateM maintainer, who
suggested distilling the flow into a runbook, and it is contributed here as a
worked non-benchmark example: a graph whose gates are all real verification,
plus notes on which parts of the flow the runbook format expressed directly and
which parts had to stay inside our own commands.

## Files

- `construction-daily-report.yaml` is the graph.
- The commands are illustrative. Every `run:` invokes one subcommand of a thin
  wrapper, `./tools/daily-report-gate.sh`, over an existing pipeline. Each
  subcommand calls a module that already exists, writes one small JSON verdict
  file, and exits 0 or non-zero. The wrapper is deliberately language-neutral
  here; nothing in the graph depends on its implementation language.
- `REPORT_DAY` is the ISO day being produced. The spec belongs at the root of
  the repository that owns the wrapper, because `predicate.path` and command
  `cwd` resolve against the spec's own directory (`statem/core.py:1398-1412`).

Verdict files written by the wrapper and read by the graph:

| File | Shape |
| --- | --- |
| `inputs.json` | `{"status": "anchored", "unanchored_count": 0}` |
| `proposal.json` | the model's day file; data only, no verification claims |
| `validation.json` | `{"verdict": "accepted" / "rejected", "refusals": [...]}` |
| `attempts.json` | `{"origin_hash_pinned": true, "used": 1, "cap": 2}` |
| `provenance.json` | `{"unproven_fields": 0, "quotes_rechecked": N}` |
| `review.json` | `{"decision": "approved" / "changes-requested" / "rejected"}` |

## The flow

```text
prepare -> propose -> validate -> human_review -> handoff
                        ^   |          |
                        |   v          v
                        +- repair    escalate
```

The diagram is simplified: it shows seven of the nine edges. The two it leaves
out are `validate -> escalate`, taken when the attempt cap is already exhausted,
and `human_review -> repair`, taken when the reviewer requests changes.

1. **prepare** anchors every input before any text exists. Sources are hashed
   and recorded first, so a quote written later can be re-located byte for byte
   in bytes that were frozen before the model wrote anything.
2. **propose** lets the model write data only, at a single allowed path. Every
   printed field is either a literal quote carrying its own provenance or an
   explicitly labelled gap. The model never asserts that anything was verified.
3. **validate** runs the deterministic validator: 27 fail-closed field checks,
   no LLM involved, whose verdict the model has no vote in.
4. **repair** hands the refusals back verbatim, bounded by an attempt cap keyed
   to the pinned hash of the origin turn.
5. **human_review** is where a person reads the rendered report against the
   refusal history and the anchored sources, and records a decision.
6. **handoff** archives the accepted day as a verified golden trajectory: the
   accepted bytes, the anchored sources, and the refusal history relabelled as
   a first-try success, plus the dataset split the day belongs to. Evaluation
   days stay disjoint from training days.
7. **escalate** is the terminal node for a day that did not converge.

## What mapped cleanly

**Phase to node.** The pipeline is a frozen linear list of steps in code, with
no DSL and no external configuration. It collapses into seven nodes because
several fine-grained steps share one contract: three input steps are one
`prepare`, three output steps are one `handoff`. The real gain from the
translation is that the graph stops being linear. The correction loop lived
outside the step machine as an exception path; here it is a first-class edge,
and exhausting the cap is an explicit terminal node instead of a re-raised
error.

**Deterministic check to `command`.** `command` is one of the two check types
that verify deterministically on their own, with no human and no model in the
loop: it runs the shell command and passes on exit code 0
(`statem/core.py:610-637`, decided at `:637`). Nothing beyond the exit code is
read. That is enough, because the rigor does not need to live in
the state engine, it needs to live in the verifier. The whole adapter is
translating a verdict into an exit code, which is also how this repository
solves it when it needs real verification: the family helper is invoked through
`type: command` in
`examples/terminal-bench-2.1-git-webserver-deploy-family.yaml:86-87`.

**Verdict read as data to `predicate`.** `predicate`
(`statem/core.py:690-732`) is declarative, involves no shell, and takes no word
from the agent. The graph uses it deliberately *in pairs* with `command` at
every critical boundary: the command supplies the exit code, the predicate
reads the written verdict. That is not redundancy. It is the difference between
"the wrapper exited 0" and "the wrapper wrote `verdict: accepted`". A wrapper
that exits 0 without writing a verdict passes the first and fails the second.

**Correction loop to a node plus a back edge.** The topology translated without
loss. The retry semantics help here: on a blocked transition `current` and
`current_entry_id` do not change (`statem/core.py:294-308`), and `entry_id` is
renewed only on a successful transition (`core.py:326-327`), which preserves
attempt identity across retries.

**`on_failure: continue` on the validator.** The validator must *run* even when
it rejects, because its verdict file is what routes the run to `repair`. A
blocking item there would make a rejection unroutable by any edge, including
the repair edge. `on_failure: continue` (`core.py:1115-1116`, effective in
`_has_blocking_failure` at `core.py:1373-1374`) is exactly right, and it is the
same construction the benchmark runbook already uses for its stateful gate
(`examples/terminal-bench-2.1-git-webserver-deploy-family.yaml:89`).

**Batched failures.** `_run_items` is a list comprehension with no
short-circuit (`statem/core.py:558-562`): every item in the stage runs even
after one fails, and blocking is evaluated afterwards. The agent receives the
full `results` array with passes and failures together, inside a JSON payload
carrying `stage` and a distinct exit code. For a bounded repair loop this is
the difference between spending an attempt per defect and spending one attempt
on the whole list, and it is the format we are adopting on our side.

## What lives inside the wrapper commands

Three properties of the flow could not be stated in the runbook, so they ended
up inside the wrapper and are invisible to the engine. Each one is written up
below with what we tried, why the format could not carry it, and the smallest
extension that would. All three were discussed with the maintainer on X; what
follows records our side of that discussion, not a commitment on his.

### 1. Attempt cap keyed to the pinned origin hash

**What we wanted to say.** "This run may enter `repair` at most twice against
the same origin bytes." A correction loop is by construction a gradient against
its own judge: with unbounded attempts, the shortest path to a green gate stops
being *write the correct day* and becomes *find the shape the check does not
catch*.

**Why it did not fit.** The engine has no counter. The runtime state schema
(`statem/core.py:151-161`) has no attempt field, and `goto_blocked` events are
written to history (`core.py:301`, `core.py:317`) and rendered by
`statem history` (`cli.py:309`), but no decision path reads them back: nothing
counts them, so no ceiling can be enforced from them. Unbounded retry is the
default and there is no way to declare otherwise.

The subtler half is the key. Our counter is bound to the hash of the bytes the
turn produced *before* any correction, because the correction rewrites the
file: with current bytes as the key, every correction would start a new
sequence, the count would reset, and the cap would never bite. Neither the
counter nor the key has a representation in the format.

**Where it ended up.** Entirely inside `record-attempt --cap 2 --pin-origin`
and the `attempts-remaining` conditions on the edges. The runbook shows the
topology of the cap; the cap itself is opaque to the engine.

**Smallest extension that would carry it.** Two optional keys on an edge:

```yaml
- from: repair
  to: validate
  max_attempts: 2
  attempt_key_command: "./tools/daily-report-gate.sh origin-hash --day $REPORT_DAY"
```

`max_attempts` counts `goto` attempts on that edge and blocks when exhausted;
`attempt_key_command` lets the runbook author define what counts as the *same*
attempt (the command's stdout is the key; when the key changes, the count
resets). The history already records everything needed — it is only never
counted. Keeping both keys optional preserves every existing runbook.

### 2. Fail-closed spec validation

**What we wanted.** A guarantee that a runbook cannot lose a gate to a typo. On
our side that is an explicit lock: a coverage pass runs before anything is
assembled and requires each of the 27 field checks to be in one of exactly two
states, configured or waived with a written reason. A missing key is an error.
A present but empty key is also an error, because an empty key is the check
switched off with the key left in place to disguise it. Configured *and* waived
at the same time is an error for ambiguity.

**Why it did not fit.** `_validate_items` (`statem/core.py:1120-1138`) checks
the `type`, the presence of `run` / `path` / `items`, and the value of
`on_failure`. Unknown keys are not rejected anywhere in the package. The
clearest evidence is in the code itself: `HOOK_KEYS` is declared at
`statem/core.py:33` and never referenced again — the intent to validate node
keys is already there, unfinished.

The practical consequence is that `befor_transfer:` produces a node with no
gate at all and `statem validate --json` still answers `ok: true`. There is a
live instance in the tree, offered as a demonstration rather than as a bug
report: `confirmation: none` appears in three checklists of the benchmark runbook
(`examples/terminal-bench-2.1-git-webserver-deploy-family.yaml:20`, `:92`,
`:107`) and no line of `core.py` reads a `confirmation` key. That graph behaves
as intended under `--yes`, so nothing is broken there; it is simply the
clearest available proof that an unsupported key reaches no error path. For a
tool whose value proposition is blocking invalid transitions, that failure mode
is expensive: the gate does not fail, it ceases to exist.

**Where it ended up.** Outside the format. The graph compensates with the
blocking `check-coverage` command, first in `validate`'s `before_transfer` —
but that protects *our* check configuration, not the runbook against a typo in
itself. If `before_transfer` were misspelled on `human_review`, the handoff
battery would survive on the edge while the node gate vanished silently.

**Smallest extension that would carry it.** Rejecting, at validation time, node
and item keys that the loader never reads. `HOOK_KEYS` at `statem/core.py:33`
is the obvious seed for the allowed set, but the exact set is yours to draw:
it has to cover the aliases already accepted and the keys the loader itself
injects during normalization, so the check reads more naturally against the raw
mapping than against the normalized node. If backward compatibility is a
concern, a `strict: true` top-level key or `statem validate --strict` delivers
the benefit without touching existing runbooks. This is the highest
value-to-effort change we found in the repository.

### 3. `goto --dry-run` across all three stages

**What we wanted.** All refusals of a round returned to the model in a single
correction turn.

**Why it did not fit — and here the engine is ahead of us, with one limit.**
As noted above, the batching inside a stage is excellent. The limit is that the
batch is per stage, not per transition. `goto` runs three sequential stages:
pre-leave (`before_transfer` plus dynamic checks plus `condition`,
`statem/core.py:289-293`), leave (`out_hook` plus the edge `hook`,
`core.py:310-312`), and entry (the destination `in_hook`, `core.py:330`). Stage
two only runs if stage one passed completely. So an `out_hook` failure only
surfaces on the attempt *after* the one where `before_transfer` was fixed. With
a cap of two attempts, half the budget can go to discovering the list of
defects instead of correcting it.

Two smaller breaks in the batch: `checklist` short-circuits on the first
unconfirmed item (`core.py:604-607`), so a six-item checklist with three
problems reports one per round; and on a *blocked* transition text mode prints
only the message and drops `exc.details` (`cli.py:36-37`), which is where
`stage` and `results` live. A successful `goto` does print the interesting
results in text mode (`cli.py:293-295`), so the loss is specific to the path
where the batch matters most.

**Where it ended up.** Everything that can be gated is concentrated in
`before_transfer` and edge `condition` — the two stages that run together — and
`in_hook` is used only to record. The six-item battery on the handoff edge is a
single pass on purpose.

**Smallest extension that would carry it.** `statem goto TARGET --dry-run`:
walk all three stages with no commit effects and no pointer movement, returning
the aggregated `results[]` of the three. The engine already has everything it
needs; what is missing is the flag and a path that does not persist. For an
agent it is the difference between "I found a defect" and "I found the list of
defects".

## Guarding the unrecoverable handoff

The maintainer's advice on this flow was that unrecoverable handoffs should be
checked carefully before entering the next step, and that the rest can be
figured out during development and eval on a separate golden set. That advice
shaped the graph, and it named the right boundary.

There is exactly one irreversible act in this flow, and it is not publishing
the document: a wrong document is corrected with an erratum. The irreversible
act is **archiving the day as a golden trajectory**. A wrong day archived there
does not just ship once, it becomes training data and teaches the wrong thing
permanently. A premature handoff in a legally meaningful document is bad; a
premature handoff in a training-data factory is bad and compounds.

So the full battery lives on the `human_review -> handoff` edge rather than
being spread along the path: approved human decision, strict revalidation over
the **final** bytes, byte-exact provenance recomputation, chained derivation
seal, and two predicates reading the verdicts as **data** so a wrapper that
exits 0 without writing a verdict cannot pass. Six items, one pass, at the last
point that still runs before the commit.

That "last point" is worth flagging, because it is not the intuitive place. The
natural home for an *entry* gate is the destination's `in_hook` — but `goto`
writes `state["current"] = target` and persists it to disk
(`statem/core.py:326-329`) *before* running the destination `in_hook`
(`core.py:330`), and a blocking failure there raises at `core.py:347-351` with
the pointer already moved. `README.md:174` states the opposite ("If a blocking
check fails, the agent remains in the current state"), which holds for the
pre-leave and leave stages but not for `in_hook`. Today the edge `condition` is
the only construct that actually runs *before* entering, so that is where an
unrecoverable handoff has to be guarded. Moving the state write to after a
successful `in_hook` would make the README sentence true everywhere and give
the advice its natural home.

The second half of the advice — eval on a separate golden set — is why the
`handoff` node records the dataset split at archive time, before any distilled
model exists and therefore before anyone has a reason to move a hard day across
the line. The split is a property of the day, assigned at origin, not a
partition chosen later. Evaluation days still go through the same deterministic
battery: a golden day that fails strict revalidation is not gold, it is debt.
And the registry stores the refusal history alongside the accepted bytes,
because that history is the difference between "the model got it right" and
"the model got it wrong in a specific way and the verifier caught it".

## Constraints the graph works within

Two further engine behaviors dictated the shape of the file, noted here so the
graph does not read as arbitrary. Neither carries a request.

**`predicate.path` is static.** `_resolve_path` (`statem/core.py:1408-1412`)
applies `expanduser()` and resolves relative to the spec's directory. There is
no `expandvars`, no `run_id` or `entry_id` interpolation, not even for the
`STATEM_*` variables the engine exports to commands (`core.py:1318-1326`). A
predicate therefore cannot address the artifact of the current run, so the
wrapper mirrors the day's verdicts into a fixed workspace,
`.statem-daily-report/current/`, and the predicates address that. Adding
`os.path.expandvars` before `expanduser`, or substituting `{run_id}` /
`{entry_id}` in `path`, would remove the mirror.

**`before_transfer` is edge-blind.** A node's `before_transfer` items are read
from the node, not from the edge (`statem/core.py:289`), so the same items run
on every outgoing transition. The target is already resolved by then
(`core.py:283`); the node's items simply are not parameterised by it — within
the pre-leave stage, only the edge `condition` (`core.py:292`) is. A gate that
must reject the path to `handoff` while allowing the path back to `repair`
cannot live on the node at all. The node keeps only what
holds on any exit — that a human decision was recorded — and the battery moved
to the edge. This one worked out well: the forced separation is clearer than
the first design we drew.

**Check types that verify nothing under `--yes`.** `manual` and `checklist`
return passed with the literal outputs `auto-confirmed yes` /
`auto-confirmed checklist` under `--yes` (`core.py:587-588`, `:600-601`), and
without `--yes` and without a TTY they always fail (`core.py:589-590`,
`:602-603`), which is always the case for an unattended agent. So the graph
contains exactly one `manual`, on the human sign-off, where self-attestation is
the honest semantics — and even there it is not the load-bearing gate. There
are no `checklist` items, and no `llm_review`: without `run:` in the YAML and
without `STATEM_LLM_REVIEW_CMD` in the environment, `llm_review` degrades
silently into `manual` (`core.py:644-648`), and a gate that can disappear
without a signal does not belong in a flow with legal weight.

## Method note

This runbook was produced by static analysis of StateM at commit `8f84474`;
every key used was traced to the line of `statem/core.py` that reads it, and
the constraints of the bundled parser were treated as design constraints (no
blank lines and no `#` lines inside a block scalar, since
`statem/miniyaml.py:44-46` drops them before block scalars are assembled at
`:139-151`; spaces only for indentation, `:42-43`; `run:` values double-quoted
with no inner quotes or backslashes, since `_parse_scalar` passes quoted values
through `ast.literal_eval` at `miniyaml.py:199-203`; no inline comments; no
list item containing a bare `:`, which would become a mapping at
`miniyaml.py:174-178`).

It has **not** been validated by running `statem validate`, because the study
that produced it was scoped to reading the code rather than executing it. What
remains unverified is therefore that the file loads without error in the real
parser and that `statem validate --json` answers `ok: true`; both are one
command for a maintainer, and we will gladly adjust the file for anything that
surfaces.
