# StateM nested runbook v1 and repair semantics

## Decision boundary

StateM keeps a thin global backbone. Complexity is admitted only when a
comparison or repeated failure attribution shows that the thin path is
insufficient. Extensibility is a design property, not a requirement to activate
every available control in a benchmark run.

The default reviewer remains a bounded role with inline, conditionally routed
practice composition. A reviewer-specific StateM graph is justified only when
a family repeatedly omits required checks despite a fixed inline practice, or
when review itself has a meaningful multi-stage lifecycle with recoverable
feedback. A reviewer graph is not the default merely because nested runbooks
exist.

## Nested runbook v1

The first core increment adds a recoverable, auditable subgraph call. A
`runbook` hook item can be the first item in `in_hook`, `before_transfer`, or
`out_hook`:

```yaml
- type: runbook
  runbook: family-review.yaml
  return_states:
    - done
  role: reviewer
```

A selector can route a parent entry to one allowlisted child or to `skip`:

```yaml
- type: runbook
  selector:
    path: route.json
    json_path: family
  routes:
    stateful_service: service-review.yaml
  default: skip
  return_states:
    - done
```

The selected route is bound to the parent node entry. Resuming the same entry
does not suddenly load a different practice if the selector file changes. This
preserves the thin-path decision and prevents context drift.

The child runs in the same durable StateM run. The runtime stores a bounded
call stack with parent and child spec hashes, parent node and entry identity,
hook phase, resume action, role metadata, and a return-state allowlist. `statem
return` is accepted only at an allowed child state. It restores the exact parent
entry and resumes the interrupted hook or transfer. A completed-call receipt
prevents re-entering the child or replaying hook items that preceded it; v1
therefore requires the call to be the first hook item. Artifact checks remain
ordinary parent predicates or receipts rather than a second artifact protocol
inside the call primitive.

Active child source drift fails closed. Parent source drift is rejected at
return. The maximum nesting depth is four. `role` is metadata in v1: the core
does not silently spawn an agent, create a worktree, or grant new permissions.

## Repair actions

The recovery vocabulary distinguishes the abstraction layer of the failure:

- **Revise** keeps the current direction and context. Use it when evidence
  identifies a local, non-destructive, deadline-feasible repair or missing
  validation delta. Preserve the candidate and add or correct only what the
  attribution supports.
- **Rebranch** abandons a defective high-level direction while preserving
  accepted evidence and the immutable baseline. It gives an orchestrator a
  fresh search context or isolated candidate branch. Rebranch is appropriate
  when repeated local repairs cannot falsify the governing assumption, or
  when the failure belongs to plan selection rather than implementation
  detail. The v1 core records this semantic boundary but does not implement
  automatic workspace branching.
- **Rollback** restores an immutable known-good snapshot. It is reserved for
  destructive or provenance-invalid changes, an unsafe candidate that cannot
  be repaired within the remaining budget, or explicit transaction recovery.
  Reviewer concern, incomplete evidence, and an ordinary fixable regression
  are not rollback conditions.

Quarantine remains an evidence-preserving evaluation state: it isolates a
candidate without promoting it or erasing it. The preferred order for a local
regression is revise, then quarantine if independent evaluation is needed.
Rollback is the terminal recovery mechanism, not a routine search step.

## Family and practice policy

Practices should have a compact solver-facing form and a detailed
reviewer-facing form. Routing is primarily within a task family. Cross-family
promotion requires an explicit transferable invariant, not surface similarity.
The parent runbook should carry only the trigger and compact obligations; a
nested family runbook may expand lifecycle states when the family genuinely
needs them.

For Terminal-Bench development, the admission order is:

1. keep the global direct path unchanged;
2. add a narrow family trigger and compact practice;
3. compare matched direct and controlled cells;
4. add a nested family graph only if inline composition cannot express the
   observed lifecycle or repeatedly misses the same required review;
5. add a reviewer-specific graph only after reviewer-level evidence, not from
   solver failure alone.

## Validation completed

The focused CLI suite covers static calls, selector skip and route binding,
return-state blocking, same-entry restoration, interrupted transfer resumption
without consuming a second edge attempt, source-hash failure, and hook-order
validation. All 43 CLI tests pass. The repository-wide discovery ran 817 tests:
813 passed, three skipped, and one unrelated error remained because the dirty
fresh-score ledger is version 4 while its existing gate accepts only versions 2
or 3. The pre-existing CLI suite remains green, so runbooks without a `runbook`
hook item retain their old path.

## Deferred choices

The following remain deliberately outside v1 until comparison evidence exists:

- automatic multi-agent spawning from a child runbook;
- worktree or artifact-transaction creation by core;
- automatic Rebranch policy and candidate portfolio ranking;
- reviewer graphs by default;
- arbitrary calls from edge conditions or edge side-effect hooks;
- repeated invocation of the same child from the same parent entry.

The next experiment should be one family whose inline practice has a known
repeated lifecycle omission. It should compare the current inline route against
the smallest nested family graph while keeping solver prompt, model, task,
timeout, and reviewer practice content fixed.
