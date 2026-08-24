# TB3 v4p71 ERP Daytona u3 infrastructure result

## Classification

- Task: `terminal-bench/erp-procurement-planning`
- Cell: adapted compact-practice development
- Reward validity: invalid; no verifier reward was produced
- Protocol validity: invalid; the agent never started
- Model usage and API cost: zero

## Failure

The Daytona environment build failed before agent startup while fetching the
PostgreSQL repository signing key. The connection was reset by the peer. This
is the same public environment-build boundary observed in u2, so a further
Daytona retry is not authorized without a new infrastructure discriminator.

This result is not a `0 -> 0` control comparison and says nothing about the ERP
compact-practice hypothesis. The next valid attempt must move to a different
x86 execution lane or first demonstrate that the failing build dependency is
reachable.

## Search policy

A single reward-valid `0 -> 0` closes only the tested comparison. Continued
adapted search is allowed when the completed attempt narrows failure ownership
and the next attempt has a new falsifiable public discriminator, a meaningful
validation delta, and deadline-feasible expected information gain. Repeating
an identical setup failure does not meet that standard.

## Preservation

- Source and backup regular files: 9 each
- Source and backup bytes: 231,741 each
- Deterministic relative-path/content tree SHA-256, both copies:
  `3be83ac000eb938e45f77b98f24d87e59757ec15480b0e7dce985a00be6c7d78`
- `rsync -nrc --delete`: empty
