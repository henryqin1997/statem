# TB3 Phase-1 Family Development Loop

## Objective

Increase the Terminal-Bench 3.0 raw score by 15 percentage points without
task-specific routing or negative transfer. A development cell may diagnose or
validate a generic control, but it does not count toward the score target. Only
standard-timeout, no-retry, fresh raw cells that were not used to develop the
tested control contribute to the phase-1 score ledger.

The public GPT-5.6 Sol Max row is a selection prior, not a causal control: it
used Codex 0.144.1, while current cells use a newer Codex build. A score claim
therefore requires a matched direct baseline with the same model, Codex,
platform class, timeout, retry policy, and task sample. The final +15 claim must
come from a sufficiently broad matched batch, not the difference between the
public historical row and a handful of current k=1 cells.

## Versioned Control Increments

### v4p31 failure closure

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

### v4p32 progress and replay coverage

Three independent adapted cells showed that node/entry identity alone can
mistake ongoing work inside a long `solve` stage for a stall. v4p32 therefore
adds a low-cost continuation witness over state/entry, pruned artifact metadata,
and bounded milestone receipts. This witness can authorize another bounded
resume but cannot authorize correctness; snapshot, replay, and promotion still
use content SHA identities.

Session-window also showed that requirement-id coverage can conceal an omitted
consumer stratum. v4p32 binds each adapter replay check to exact
`covered_strata` and rejects the plan unless their union covers every immutable
preflight `required_strata` value.

The native direct baseline uses `AuthNoSessionCodex`. It delegates the task
instruction unchanged to Harbor Codex, converts the session to ATIF, and then
requires raw-session removal. It is an evidence harness, not a StateM route.

### v4p34 deadline-aware review routing

Two independent v4p33 Bun cells completed `solve -> falsify -> revise` and then
ended protocol-invalid before handoff. Their direct controls both produced
valid raw zeroes, while the StateM cells never reached the verifier. This was
not a false semantic block: the independent falsifier identified a real
candidate generalization gap. The lifecycle defect was that review routing
opened another revision without checking whether its second review, replay,
and handoff could fit the remaining official deadline.

v4p34 separates the family full-cycle retry reserve from a smaller in-cycle
revision reserve. The host checks that reserve before routing a falsified
candidate to `revise`. If it does not fit, the candidate is quarantined for
final replay and handoff. The gate does not rewrite the reviewer verdict,
promote the candidate, or roll back the artifact. Historical runbooks that do
not request deadline-aware review routing retain their prior behavior.

## Family Queue

Priority is expected raw gain multiplied by attribution quality, family reuse,
resource feasibility, and the probability that the missing capability belongs
to StateM rather than the base model. Public 0/5 and 1/5 CPU tasks lead only
when their visible failure surface is plausibly controllable by contract,
practice, validation, or lifecycle policy. GPU-bound, very expensive, deeply
specialized, or likely capability-ceiling tasks do not displace cheaper cells.

| Priority | Task | Family | Public Sol prior | Cell purpose |
| --- | --- | --- | --- | --- |
| 1 | `mvcc-lsm-compaction` | stateful-lifecycle | 0/5 | High-value family development; earlier StateM raw 1/1 is feasibility evidence only. |
| 2 | `session-window-debug` | stateful-lifecycle | 0/5 | Same-family sentinel; earlier fresh StateM raw 1/1 is not an estimate. |
| 3 | `html-js-filter` | structured-transformation | 1/5 | Extended-time diagnostic for lifecycle and failure-closure completeness. |
| 4 | `interleaved-vigenere` | structured-transformation | 1/5 | Same-family standard-timeout sentinel; v4p30 raw 1/1. |
| 5 | `vf2-speedup-networkx` | algorithm-performance | 1/5 | Expensive performance/semantic family cell; earlier StateM raw 1/1. |
| 6 | `lake-temp-glm` | numerical-model | 1/5 | Numerical sealed-gap attribution; v4p29 and v4p30 remained 0. |
| 7 | `cad-model` | simulation-artifact | 1/5 | Deferred until public dimension/projection attribution is unambiguous. |

For fresh `0/5` selection, use matched `k=1` direct/StateM pairs as triage.
Promoted controls then receive matched `k=5` estimation cells. A task remains
active only if a development attempt adds at least one machine-auditable signal:
a new reproducible discriminator, a narrower failure owner, a candidate-blind
validation delta bound before retry, or a public-check/artifact improvement.
Two consecutive attempts without such progress park the task and advance the
queue. This prevents repeated search on model-capability or hardware ceilings
from consuming the low-cost lanes.

Before allocating a `0/5` cell, write a bottleneck preflight with the dominant
limit prior, evidence basis, cheapest public discriminator, expected API/wall
cost, hardware feasibility, and owning control layer. The prior must distinguish
StateM-controllable workflow failures, base-model capability limits,
hardware/resource limits, mixed failures, and unresolved failures. A low public
score alone is not evidence that StateM can help. Capability- or hardware-led
cells remain behind cheap workflow-led cells unless a new generic hypothesis or
feasible resource change makes the next observation informative.

This preflight is an admission gate, not documentation after the fact. It must
also name the expected observable progress and the condition that parks the
task. Allocate lanes by expected raw-score gain per API dollar and lane-hour,
subject to high StateM ownership. Cheap CPU cells whose failure is plausibly in
contract, practice, validation, or lifecycle control lead the queue. A public
`0/5` task dominated by specialist capability, unavailable hardware, or an
unobservable acceptance surface does not lead merely because its score upside
is large.

Develop progress means more than another trajectory. Continue only when the
last cell changes the posterior over failure ownership or advances a
machine-auditable artifact: a reproducible discriminator, a narrower owner, a
candidate-blind validation delta, a public-check improvement, or an independently
replayable milestone. Two consecutive attempts without one of these signals
park the task. A successful internal test with no new coverage or attribution
does not reset this counter.

The queue contract is currently structured but must not remain prompt-only.
The minimal enforcement point is a benchmark-orchestration prelaunch gate, not
StateM core and not task-agent context. It issues a receipt bound to the queue
hash, task, frozen control, mode, platform, bottleneck prior, owner, hardware
feasibility, cheapest discriminator, estimated API/wall budget, observable
progress target, park condition, and hypothesis-scoped no-progress count. The
receipt decision is `admit`, `defer`, or `reject`. This gate validates that the
selection argument is complete and internally consistent; it does not pretend
that a semantic prior is mechanically proven. Because the receipt remains
host-side, it adds no task-solver cognitive load and cannot leak selection
metadata into the solution trajectory.

The no-progress counter is hypothesis-scoped. A parked task reopens only when a
different task supplies a new generic control, a cheaper public discriminator,
new feasible hardware, or a materially narrower owner. Re-running the same
workflow with more context or budget is not, by itself, a new hypothesis.

The initial fresh priority order is `bun-sourcemap-leak`, then
`production-planning`, `cargo-flight-dispatch`, and
`foodstuff-beta-activity`. This is not a price-only order: hardware/platform
feasibility and StateM control ownership lead, then the cheapest public
discriminator and expected raw gain, then API and wall cost. Foodstuff is
cheaper in API dollars but has a much longer reserve and a larger base-model
capability component. `roy-polymorph-cn`,
`gsea-proteomics`, and `fix-uautomizer-soundness` remain available but start
behind those cells because scientific-domain or program-analysis capability may
dominate their failures. This is a metadata prior only; matched evidence may
reorder the queue.

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
8. Run `risk-scorer-replay`, whose public Sol prior is 5/5, as a zero-regression
   sentinel before a family increment is promoted. Passing reward alone is not
   enough: record route, protocol validity, cost, and wall-time deltas against a
   matched direct baseline.
9. Classify every candidate's dominant limit before allocating another cell:
   StateM-controllable workflow error, base-model capability, hardware/resource,
   infrastructure, or unresolved. Continue only while the validation delta
   demonstrates new information or observable artifact progress.

## Current Lanes

- Completed local: extended-time `html-js-filter` v4p31 diagnostic. It found a
  concrete implementation owner and append-only validation delta, then stopped
  inside the second solve cycle. It is adapted, protocol-invalid, preserved,
  and excluded from score.
- Completed remote A: `mvcc-lsm-compaction` v4p32 produced a preflight,
  candidate snapshot, and stratum-complete replay, then remained in `solve`
  because uppercase reviewer requirement ids failed a lowercase-only mechanical
  gate. This is substantive generic progress plus a host receipt-normalization
  defect, not a lead-solver failure or raw score. v4p33 canonicalizes identifier
  case before validation and rejects collisions after canonicalization.
- Completed remote B: `session-window-debug` v4p32 final adapted cell. It made
  no candidate/preflight progress on its second attempt and is parked until a
  new generic hypothesis arrives from another task.
- Local: `bun-sourcemap-leak` native direct k=1, the first half of a predeclared
  local ARM64 fresh pair. Its v4p32 StateM half runs only after the direct cell
  is preserved so local resource contention cannot change the comparison.

After the two remote adapted cells exit, the two x86 lanes run a concurrent
`bun-sourcemap-leak` direct/StateM k=1 pair. Every fresh-score candidate receives
a matched direct-control cell before its StateM cell is interpreted as gain.
The authoritative preallocated pair identities and eligibility fields are in
`20260820-tb3-phase1-fresh-score-ledger.yaml`.

Current v4p34 lanes are one local extended-time adapted Bun diagnostic plus a
standard-timeout AWS x86 matched direct/StateM `production-planning` k=1 pair.
Both StateM containers loaded the canonical 35-file v4p34 manifest; the direct
container has no StateM manifest. Source remains frozen until all three jobs
exit and are preserved.
