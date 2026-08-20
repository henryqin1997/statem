# TB3 v4p31 Phase-1 Family Development Loop

## Objective

Increase the Terminal-Bench 3.0 raw score by 15 percentage points without
task-specific routing or negative transfer. A development cell may diagnose or
validate a generic control, but it does not count toward the score target. Only
standard-timeout, no-retry, fresh raw cells that were not used to develop the
tested control contribute to the phase-1 score ledger.

## v4p31 Control Increment

The v4p31 runbook adds three host-validated controls adapted from the
Terminal-Bench 2.1 deadline discipline:

1. `failure ownership`: every failed replay names one bounded failure class and
   its predetermined owner. Lead, test-plan, and contract-authority defects may
   consume a task-agent retry. Adapter, host, sealed-acceptance, and
   infrastructure defects hand off to the owning control instead.
2. `validation delta`: a retry must preserve prior obligations and append one
   discriminating public check. The next candidate-blind plan must carry that
   exact check before candidate work begins.
3. `deadline-feasible retry`: information gain is necessary but insufficient.
   The remaining benchmark deadline must also cover the selected family's full
   solve, review, replay, receipt, and handoff reserve.

The family router is deterministic from the already-bound reviewer profile.
Its contract scope cannot weaken the task contract, while its practice scope
prevents unrelated procedural memory from leaking across families.

## Family Queue

Priority is expected raw gain multiplied by attribution quality, family reuse,
and resource feasibility. Public 0/5 and 1/5 CPU tasks lead the queue.

| Priority | Task | Family | Public Sol prior | Cell purpose |
| --- | --- | --- | --- | --- |
| 1 | `mvcc-lsm-compaction` | stateful-lifecycle | 0/5 | High-value family development; earlier StateM raw 1/1 is feasibility evidence only. |
| 2 | `session-window-debug` | stateful-lifecycle | 0/5 | Same-family sentinel; earlier fresh StateM raw 1/1 is not an estimate. |
| 3 | `html-js-filter` | structured-transformation | 1/5 | Extended-time diagnostic for lifecycle and failure-closure completeness. |
| 4 | `interleaved-vigenere` | structured-transformation | 1/5 | Same-family standard-timeout sentinel; v4p30 raw 1/1. |
| 5 | `vf2-speedup-networkx` | algorithm-performance | 1/5 | Expensive performance/semantic family cell; earlier StateM raw 1/1. |
| 6 | `lake-temp-glm` | numerical-model | 1/5 | Numerical sealed-gap attribution; v4p29 and v4p30 remained 0. |
| 7 | `cad-model` | simulation-artifact | 1/5 | Deferred until public dimension/projection attribution is unambiguous. |

After each family repair, validate on a same-family sentinel and then on a
fresh holdout. A task used to author or select the repair is permanently marked
adaptive and cannot later become that repair's holdout.

## Loop Policy

1. Keep active jobs read-only. Never deploy source while a runner, reviewer,
   probe, Harbor process, or experiment container is active.
2. Back up every completed source job and verify regular-file count, total
   bytes, and deterministic relative-path tree SHA-256.
3. Attribute failures to implementation, test plan, contract authority,
   evidence projection, lifecycle, sealed uncertainty, or infrastructure.
4. Change the owning layer only. Version every generic source increment, run
   focused tests and strict runbook validation, and archive it in private Git.
5. Prefer revise, then quarantine. Roll back only for a destructive candidate,
   hard provenance error, or a repair that cannot be made safely in place.
6. Keep reward validity and protocol validity independent. Timeout diagnostics
   never become raw score observations.
7. Maintain one development ledger and one fresh raw score ledger. Stop only at
   a verified +15-point net target, a hard provider/auth/system failure, or a
   user stop.

## Initial Lanes

- Local: extended-time `html-js-filter` diagnostic under v4p31. This is adapted
  and cannot count toward the score target.
- Remote A: `mvcc-lsm-compaction` v4p31 family-closure development cell.
- Remote B: `session-window-debug` v4p31 same-family sentinel. It is a repeated
  known task and is therefore evidence about regression, not a fresh holdout.

The first fresh-score batch is selected only after these cells establish that
failure feedback closes correctly and no stateful-lifecycle sentinel regresses.
