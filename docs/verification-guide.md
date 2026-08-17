# Advanced verification with StateM

This guide collects the verification patterns used by the larger StateM runbooks. Start with the root [README](../README.md) for installation and basic runbook syntax; use this document when a workflow needs evidence-aware gates, adaptive checks, or benchmark-grade auditability.

## The objective hierarchy

Verification is a means, not the mission. A runbook should make the priority order explicit:

1. Complete the real task-visible contract.
2. Exercise the final artifact through the interface promised to its consumer.
3. Record fresh evidence that the artifact satisfies that contract.
4. Use gates and reviewers to diagnose remaining gaps.

A failed gate is feedback for repair. Do not weaken the required artifact, exploit checker assumptions, inspect hidden benchmark material, or optimize for a gate's wording at the expense of real correctness.

## Three levels of checks

### 1. Static transition gates

Put invariants known at authoring time in `before_transfer`. These gates should be small, deterministic, and local to the state boundary.

```yaml
before_transfer:
  - type: predicate
    path: ../dist/result.json
    exists: true
    non_empty: true
  - type: command
    run: "python3 -m pytest tests/test_contract.py -q"
    timeout: 120
```

If a gate fails, the transition is aborted and the agent stays in the current node.

### 2. Current-entry dynamic checks

Use `dynamic_before_transfer` when the exact verification need becomes known only after the agent inspects or changes the task.

```yaml
dynamic_before_transfer:
  path: current_entry
  required: false
  min_items: 0
  require_reason: true
  require_basis: true
  allow_types:
    - command
    - predicate
    - checklist
    - manual
```

The agent writes a check manifest for its current node entry:

```json
{
  "basis": {
    "implementation_summary": "Changed parser handling for escaped separators"
  },
  "checks": [
    {
      "type": "command",
      "run": "python3 -m pytest tests/test_parser.py -q",
      "reason": "Exercises the changed parser through its public API"
    }
  ]
}
```

Register and inspect it with:

```bash
statem dynamic write checks.json --agent-id implementer
statem dynamic list --json
```

Dynamic checks are scoped to one state entry. This prevents a task-specific check from silently becoming a permanent global rule.

### 3. Adaptive verifier plans

Sometimes a reusable gate is relevant but does not exactly fit the task. Do not widen the gate until it passes. Write a structured verifier plan that records:

- the borrowed gate or check family;
- why its fixed implementation is a near miss;
- the invariants that still apply;
- task-visible evidence used to design the check;
- generated positive, negative, boundary, or metamorphic checks;
- the command or probe actually executed;
- the resulting evidence and remaining uncertainty.

A dedicated evidence state can materialize the plan before final verification:

```text
solve -> evidence_check -> verify -> self_review -> handoff
   ^           |             |            |
   +-----------+-------------+--- repair--+
```

The transition out of `evidence_check` should require an execution receipt, not merely a plan.

## Choose checks from visible evidence

For benchmark or evaluation runbooks, activation should be auditable. A check may be selected from:

- the task's visible request;
- files and schemas in the workspace;
- public examples or tests provided with the task;
- behavior observed through the promised interface;
- durable notes and failures from the current run.

Do not select checks from task identifiers, hidden tests, verifier implementations, answer artifacts, or post-hoc oracle feedback recycled into future trials.

For ordinary tasks, prefer lazy escalation:

1. Start with a thin direct-solve path.
2. Run task-visible tests or the consumer command.
3. Escalate to a focused risk probe only when the task family, a visible failure, or a concrete evidence gap justifies it.
4. Keep the full check catalog outside the active prompt unless the focused guidance is insufficient.

When no check applies, record a structured `not_applicable` decision with the candidate check types considered and task-visible reasons. A temporary `deferred` decision must be resolved before final handoff.

## Evidence receipts

Expensive checks may be reused only when the receipt proves that the evidence is still valid. A useful receipt records:

- stage and check/template name;
- executed or reused status;
- command, working directory, exit code, and relevant messages;
- artifact identity or content hash;
- run id, node entry id, and timestamp;
- dependencies whose mutation invalidates the evidence.

Reusing evidence is never a silent skip. Lightweight transition gates still run, and any relevant artifact mutation invalidates the receipt.

A runbook can create a runtime anchor when the run starts and reject evidence older than that anchor. Freshness proves that a check belongs to the current attempt; it does not prove semantic correctness.

## Verify through the consumer interface

Evidence should match the final artifact's real use. File presence, syntax, and liveness are useful preconditions, but they are rarely sufficient on their own.

### Command-line and stdout contracts

- Run the installed or final executable, not an internal helper.
- Check exit status, stdout, stderr, ordering, and formatting where the task specifies them.
- Cover valid input, invalid input, empty input, and boundary values.
- Avoid shell pipelines in the gate when the observable interface can be invoked directly.

### Services and deployments

- Require readiness through the advertised client or protocol, not only an open port.
- Exercise at least one meaningful request; use write/read roundtrips for stateful services.
- Verify that the service survives the phase boundary when it must remain alive after handoff.
- For an agent-launched process, use a supervisor, `setsid`, or `nohup` when detachment is part of the contract.

### Packages and private indexes

- Install from the task-visible index URL into a fresh environment.
- Import the installed package and exercise its public API.
- Distinguish source files, built artifacts, published artifacts, and the fresh consumer install.

### Source builds

Prove three separate properties:

1. **Source identity** — release, version, legal, or archive metadata identifies the requested source.
2. **Build provenance** — logs and output paths show that the final artifact came from that source.
3. **Consumer behavior** — the installed or built artifact works through the promised interface.

A wrapper, symlink, packaged fallback, fake version string, or partial compatibility launcher does not establish source-build provenance.

### Protocol services

For gRPC or similar protocols, use generated client bindings against the live service. Confirm the task-visible schema and call real RPCs. If state is stored, include a write/read roundtrip.

### Databases and recovery

- Work on a scratch copy when testing destructive recovery.
- Preserve and identify companion files such as SQLite WAL or journal files.
- Verify schema, row-level behavior, and key invariants after recovery.
- Record which copy was inspected and which artifact is intended for handoff.

### Scientific and numerical outputs

- Check units, shapes, coordinate conventions, and numerical domains.
- Use physical or statistical sanity checks in addition to serialization checks.
- Include negative controls or perturbations when a result could pass accidentally.
- Treat import, signature, and liveness checks as residual-risk indicators, not semantic proof.

### Machine-learning artifacts

- Load the saved artifact in a fresh process.
- Exercise the documented inference or training interface.
- Check expected tensor shapes, dtype/device behavior, gradients when required, and deterministic invariants.
- Distinguish a loadable checkpoint from a semantically correct model.

### Video, image, and geometry artifacts

- Validate container/codec, resolution, duration, frame count, and decode success.
- Sample frames across the timeline rather than inspecting only the first frame.
- Check motion, event timing, coordinate transforms, and text overlays when they are part of the contract.
- Make any tolerance or target-frame precision explicit; do not turn a post-hoc benchmark observation into an undocumented universal default.

## Separate setup, gating, and persistence

Use each hook at the phase where its result is meaningful:

| Hook | Responsibility |
| --- | --- |
| `in_hook` | Restore task context, initialize state-local files, or load focused guidance |
| `before_transfer` | Decide whether the current state is ready to leave |
| `dynamic_before_transfer` | Run checks authored for the concrete current entry |
| `out_hook` | Persist current-state progress before transition |
| target `in_hook` | Initialize the newly entered state |

Do not hide state setup inside an exit gate. Conversely, do not treat a non-blocking entry message as proof that an exit obligation was satisfied.

## Bounded self-review

A final self-review can catch residual mismatches that fixed gates miss. Keep it bounded and require concrete evidence for a small set of lenses:

- `task_contract` — does the final artifact satisfy the visible request?
- `evidence_freshness` — do receipts correspond to the current artifact and attempt?
- `edge_risk` — which boundary, negative case, or operational condition is still most likely to fail?

Route concrete findings to repair. A clean review may hand off only when it cites evidence for each lens. Self-review complements typed gates; it does not replace them or become an endless review-until-clean loop.

## Context discipline for verifier loops

Repeated verification can make an agent overfit to the latest error log and forget the original request. At the entry to `verify` or `repair`, reload a small context anchor containing:

- the task-visible contract;
- current artifact identity;
- selected checks and their rationale;
- most recent evidence receipt;
- unresolved review findings;
- remaining time or resource constraints.

Keep large catalogs and raw logs in files. Load only the focused summary needed for the current state.

When route choice itself is ambiguous, an isolated router may inspect a compact request and write a small advisory decision. It must not solve the task, read hidden evidence, or own the final gate selection. Router timeout or malformed output should not trap the workflow; the main agent and normal evidence guards remain authoritative.

## Resource and deadline hygiene

Verification can damage handoff readiness if it consumes all remaining disk, time, or service lifetime. For resource-sensitive tasks:

- prefer minimal or CPU-only dependencies when sufficient;
- time-box failed installs and expensive probes;
- clean partial downloads and caches created during the attempt;
- record free-space or readiness evidence when the final verifier depends on it;
- stop escalating when the deadline requires a truthful blocker or evidence-based handoff.

## Review checklist for runbook authors

- Does each state correspond to a distinct artifact, ownership boundary, blocker, or recovery policy?
- Are checks attached to the state that owns the obligation?
- Does every blocking check test the real consumer contract or a clearly labeled precondition?
- Can a passing invariant be reused safely, and is its invalidation rule explicit?
- Are task-specific checks scoped to the current entry?
- Are benchmark routes and check selections explainable from visible evidence?
- Can the run resume after context refresh or a new checkout?
- Does handoff summarize changes, current state, fresh evidence, remaining risks, and the next command?

For full schema and transaction details, see [`design.md`](../design.md). The richer examples under [`examples/`](../examples/) show these ideas assembled into complete runbooks.
