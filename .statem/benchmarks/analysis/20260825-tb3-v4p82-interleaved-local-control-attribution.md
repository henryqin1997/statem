# TB3 interleaved local-control attribution

## Evidence boundary

This is post-result attribution for the adapted v4p29/v4p30 pair, not fresh
score evidence. V4p29 scored raw `0`; v4p30 scored raw `1`, but candidate-blind
acceptance obligations and the information-gain retry gate changed together.
Only bounded receipts and identity metadata were used.

## Temporal attribution

- The final candidate was created after the candidate-blind preflight and bound
  to its evidence receipt.
- Acceptance replay passed against candidate, snapshot, and live identities
  that all matched `tree-sha256:c43e5452...a8f2f`.
- The later reviewer decision was `revise` with no blocking regression, then the
  candidate was quarantined and identity-verified rather than rolled back.
- The information-gain gate subsequently denied another retry because its
  failure evidence was not bound. Handoff retained the same candidate identity
  with one cycle still available.

The acceptance plan therefore participated before construction and validation
of the final passing candidate. The information gate acted later as a search
termination and candidate-preservation control. Their temporal roles are
distinct even though their individual reward effects are not counterfactually
isolated.

## Scope decision

Retain the pair as a `task composite`. Do not spend another full rollout merely
to isolate the components and do not promote either to family or global scope.
Reconsider synthesis only if an independently developed task exposes the same
earliest consequential mechanism. The current evidence has no answer-shaped
selector, but component-level promotion would still carry post-hoc hack risk.
