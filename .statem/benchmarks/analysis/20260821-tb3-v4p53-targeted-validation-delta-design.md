# TB3 v4p53 targeted validation-delta control

Date: 2026-08-21

## Evidence motivating the change

The local FreeCAD impeller v4p51 matched development cell made a real first-cycle
artifact change and produced an independent geometry concern, but its second
cycle remained protocol-invalid. The retry brief and transition feedback reached
the same task context; the blocking failure was that the model did not reproduce
the prior discriminator exactly inside the next candidate-blind acceptance plan.
The existing v4p45 transaction correctly rejected the malformed repair, but it
still required the model to copy an entire receipt and make an exact one-field
edit. That is a mechanical host responsibility, not a semantic planning task.

This is development evidence only. The failed FreeCAD cell remains parked and
does not contribute a raw score replacement.

## v4p53 control

- A recoverable `validation_delta` must name one existing
  `target_requirement_id` when the v4p53 close gate is enabled.
- The recovery guard binds that target to the current immutable candidate-blind
  preflight plan before it authorizes another cycle. It never infers a target
  from prose.
- When entry-scoped transition feedback proves a planner-owned
  `acceptance_plan_gap`, the host automatically invokes the targeted repair
  transaction.
- The transaction derives the repaired receipt itself and may only append the
  exact prior discriminator to the named requirement's `required_strata`.
- Immutable raw TeamRun evidence, requirement count/order/identity, and every
  other semantic field remain unchanged. The canonical replace and receipt are
  atomic and idempotent.
- If the targeted requirement uses `adapter_replay`, the task agent must still
  supply the semantic execution method and rerun coverage. A receipt append is
  not treated as evidence that a check executed.
- Missing, unknown, duplicate, conflicting, or already-mutated targets remain
  fail-closed. Promotion independently verifies that the transaction requirement
  matches `target_requirement_id`.

## Compatibility boundary

v4p52 retains its exact seven-field validation-delta schema and prior manual
transaction behavior. Only the distinct v4p53 identity and runbook enable the
targeted schema and close gate. The frozen v4p52 deployment currently running on
the remote ERP cell was not mutated.

## Validation

- 155 focused unit tests passed in the isolated v4p53 package and again in the
  local main worktree.
- Strict validation passed for v4p35, v4p52, and v4p53 runbooks.
- Tested negative cases include missing and unknown targets, duplicate
  requirement identities, cross-requirement binding, semantic rewrites,
  conflicting canonical evidence, repeated commits, and atomic rollback after
  write failure.
- Python compilation passed. Ruff and Black are not installed in this local
  environment, so those formatter-specific checks were unavailable.

No raw benchmark result is attributed to v4p53 yet. Deployment and an adapted
non-scoring protocol cell should occur only after the active v4p52 ERP and native
RS Archive jobs have fully exited and been archived.
