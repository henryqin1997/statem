# Terminal-Bench 3.0 Role, Authority, And Handoff Boundary

Status: design record only. Do not deploy while the v4p54 MVCC matched cell is
active. Any implementation requires a matched negative-transfer sentinel.

## Objective

Keep the lead solver informed enough to implement and self-verify the selected
family practices without turning the independent reviewer into a disclosed
answer key. Keep semantic recommendations separate from deterministic state and
artifact authority.

## Role Boundary

### Lead solver

The solver owns the task artifact, recoverable implementation search, public
probes, and candidate-bound self-verification. It receives a compact projection
of every applicable shared obligation. A useful solver-facing projection should
contain:

- `invariant`: the task-visible property that must remain true;
- `required_action`: the implementation or planning action the solver must take;
- `self_check`: the public evidence class the solver must produce before review.

The solver must bind each projected obligation to named plan sections. It does
not receive reviewer-only counterexample ordering, adversarial probe selection,
or verdict-calibration policy.

### Independent reviewer

The reviewer is read-only and candidate-bound. It receives the immutable
baseline/candidate projections, contract seal, candidate-blind acceptance plan,
selected profiles, and reviewer handbook. It independently adjudicates semantic
forks, contract authority, regressions, protection claims, and obligation
closure. It may recommend promote, revise, or a hard provenance rejection, but
it never mutates the artifact or state directly.

### Orchestrator

An intelligent orchestrator, when enabled, may recommend candidate-blind family
routing, role scheduling, lifecycle joins, and deadline-aware allocation. It
must not edit task artifacts, rewrite reviewer evidence, or directly authorize
promotion. The current solver-selected profile is therefore an input to be
checked, not an authoritative routing decision.

### Deterministic gate

StateM and host-owned gates remain the only authority for state transitions,
receipt binding, artifact identity, budget degradation, and application mode.
An intelligent role can propose a route; only a content-addressed gate may
authorize and apply it.

## Review Guarantees

The protocol can guarantee that a structured, bound reviewer concern cannot be
bypassed on the promotion path. It cannot guarantee that a model reviewer finds
every real issue or that a prose plan revision fixes the issue semantically.
Those residual risks require candidate-blind machine replay, obligation-level
assessments, and matched sentinels.

Preflight `revise_plan` must bind immutable issue ids to genuinely changed plan
sections before a proposal is accepted. Final promotion requires an independent
accept verdict plus every deterministic validity and obligation check. Review
budget or deadline degradation may convert revise to quarantine, never promote.

## Handoff Classes

Promotion and benchmark selection are different authorities. Preserve two
explicit handoff classes:

- `evaluation_only`: a quarantined candidate may be replayed and scored without
  claiming that it is safe to publish or deploy;
- `release_candidate`: requires a verified promote authorization and exact
  activated candidate identity.

A revise or quarantine route must never satisfy a release-candidate gate. This
keeps benchmark salvage available without weakening reviewer veto semantics for
real deployment.

## Minimal Validation Before Activation

1. Solver projection test: every selected obligation has invariant, action, and
   self-check fields, while reviewer-private tactics are absent.
2. Planning test: omission, duplication, reordering, or empty actionable fields
   blocks the solver plan.
3. Reviewer isolation test: reviewer cannot mutate the candidate or transition
   state and cannot read excluded solver/session material.
4. Promotion test: revise, unresolved obligation, or incomplete review cannot
   reach promote or release-candidate handoff.
5. Quarantine test: a deadline-degraded candidate can reach evaluation-only
   replay but cannot reach release-candidate handoff.
6. Matched sentinel: compare reward, protocol validity, cost, wall time, and
   lifecycle against the frozen predecessor before changing the active control.
