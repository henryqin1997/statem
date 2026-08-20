# TB3 v4p32 control repair design

## Evidence trigger

Two v4p31 stateful-lifecycle cells identified independent generic defects.

1. MVCC returned from Codex twice while continuing work in the same `solve`
   entry. The adapter treated unchanged StateM node/entry identity as no
   progress and stopped, although task artifacts and milestone receipts can
   legitimately evolve inside one long stage.
2. Session-window completed the protocol and promoted a raw-zero candidate.
   Its candidate-blind acceptance plan required a multi-way bridge stratum, but
   the adapter gate checked only requirement-id coverage. A replay could claim
   an entire requirement while omitting one of its predeclared strata.

Neither repair uses hidden-verifier output or task-specific routing.

## Minimal increment

### Composite resume progress witness

The adapter's no-progress identity becomes:

- StateM current node and entry id;
- a content-free metadata digest of task artifacts using the existing provider
  exclusions and pruned traversal; and
- stable hashes of bounded milestone receipts that may advance before a state
  transition.

A resume consumes the no-progress allowance only when this entire composite is
unchanged. Artifact or receipt progress resets the allowance. The existing cap
still terminates genuinely stalled sessions, and the official deadline remains
the hard outer bound.

The metadata digest is only a low-cost continuation witness. Candidate
identity, snapshot restore, replay, and promotion continue to use the existing
content SHA identities; the progress digest cannot authorize correctness.

### Candidate-blind stratum coverage

Every candidate-blind adapter replay check must declare both
`requirement_ids` and `covered_strata`. For each adapter-replay requirement, the
gate derives the exact allowed `required_strata` from immutable preflight
evidence. It rejects unknown strata and rejects the plan unless the union of
executed checks covers every required stratum for every referenced
requirement. Paired and analytic review obligations remain semantic and are not
forced into command-shaped proxies.

This is intentionally a coverage/provenance rule, not a claim that a declared
stratum's command is semantically correct. Independent review still owns that
judgment.

## Validation

- Focused unit tests prove same-state artifact and receipt changes reset the
  no-progress counter while an unchanged composite remains bounded.
- Acceptance replay tests reject omitted and unknown strata and preserve legacy
  non-blind replay behavior.
- Strict runbook validation and the complete focused TB3 control suite pass.
- Promotion requires an adapted cell, a same-family sentinel, and the matched
  5/5 risk-scorer zero-regression sentinel before fresh score accounting.
