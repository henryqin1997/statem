# TB3 v4p62 thin family routing design

Date: 2026-08-23

## Decision

Reset the Terminal-Bench 3 development controller to a thin default path. The
v4p61 experimental runbook has 791 lines; the v4p62 runbook has 86 lines, an
89.1% line-count reduction. Ordinary tasks receive no family practice. A
high-precision visible-instruction selector may choose at most one compact
family practice, and selection remains shadow-only by default.

This is a control-development generation, not a fresh score claim. The family
practices are `family_candidate`, `admitted: false`, and may be activated only
for explicitly adapted comparison cells until matched evidence supports
admission.

## Context boundaries

- The global solver sees the thin solve, verify, bounded self-review, and
  handoff states.
- When active, the solver sees only one compact practice: three obligations and
  one stop rule.
- Detailed checks, failure ownership, and reviewer priority are reviewer-only
  catalog data and are not injected into solver context.
- Routing uses only visible instruction signals, never task names, historical
  rewards, or hidden verifier evidence.
- Each family requires matches from two independent trigger groups. Weak words
  such as `server` alone do not activate a route.

## Family ownership

The initial catalog has four narrow candidates:

1. `stateful-lifecycle`: ownership, visibility, replay, and external commit.
2. `structured-transformation`: preservation and malformed or nested boundaries.
3. `algorithm-performance`: semantic equivalence, representative population,
   cold/warm execution, and consumer construction.
4. `numerical-model`: exact estimator or convention, analytic sanity cases,
   population, shape, and public consumer path.

These are portable family practices, not task routes. Development sample names
are retained only as provenance metadata and are not read by the selector.

## Reviewer graph decision

No independent reviewer runbook is activated in v4p62. Existing evidence shows
that bounded inline review can produce valid decisions, while the heavy path
materially increased cost and wall time on a known-positive MVCC sentinel. An
independent reviewer graph remains available through the new nested-runbook
core only after comparative evidence shows repeated omission, a genuinely
stateful reviewer lifecycle, or a family-specific reviewer flow that cannot be
expressed as a small practice composition.

## Repair semantics

- **Revise**: keep the direction and context; make the smallest recoverable
  implementation or test-plan repair.
- **Rebranch**: preserve the incumbent, summarize the falsifying evidence, and
  explore a materially different high-level direction with fresh attention.
- **Rollback**: restore an immutable known-good artifact only after destructive
  change, hard provenance failure, or inability to repair safely.

Incomplete evidence alone never justifies rollback. The thin runbook records
whether a failure belongs to implementation or validation before choosing the
next step.

## Validation

- Strict runbook validation: pass.
- Thin-family focused tests: 9/9 pass.
- Related lifecycle, promotion, and family tests: 57/57 pass.
- Nested-runbook return and source-binding tests: 4/4 pass in the frozen worktree;
  the complete core suite passed 43/43 in the main repository.
- Python compilation and whitespace validation: pass.

The broader frozen-branch test command has six fixture failures because that
branch does not contain the later untracked TeamRun example files referenced by
the current CLI test file. They are dependency-closure failures, not behavioral
failures, and are not hidden by adding unrelated fixtures to this generation.

## Next comparison

The first admissibility comparison should be an adapted known-positive
stateful-lifecycle sentinel under active compact routing, compared against its
thin/direct and v4p61 evidence. It must preserve raw reward and protocol
identity while materially reducing cost or wall-time overhead. A failed
negative-transfer sentinel blocks admission. Nested reviewer execution remains
dormant unless the inline reviewer repeatedly misses a specified family check.

## First comparison outcome

The adapted known-positive MVCC sentinel completed with raw reward `1.0`,
protocol-valid `handoff`, no error or retry, and an actual
`solve -> verify -> solve -> verify -> self_review -> handoff` revision path.
It cost `$1.0312304` and finished in about 12m42s with a 10-file source
manifest, versus `$11.610926`, about 48m04s, and 37 files for v4p61. The result
admits v4p62's thin architecture as the development baseline. The individual
stateful-lifecycle practice remains a shadow-default family candidate pending
one transfer cell and one weak-signal false-positive sentinel.
