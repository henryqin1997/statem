# Risk scorer native sentinel: infrastructure-invalid attempt

## Status

- Job: `tb3-sol-native-baseline-v1-risk-scorer-replay-k1-aws-x86-a`
- Result: no valid raw reward
- Protocol validity: invalid before task work began
- Error bucket: native baseline authentication ownership
- Tokens and API cost: none reported
- Score eligibility: excluded

## Attribution

The task image executes the agent as a non-root user and sets `HOME=/tmp`.
The native baseline adapter uploaded file authentication as root, but Harbor
did not have an explicit `default_user`, so its normal ownership correction
was skipped. Codex therefore could not read the authentication file and exited
with an authorization error before producing task evidence.

Other concurrent StateM jobs remained healthy. This is a generic non-root
container compatibility gap in the native baseline harness, not a provider
outage, model failure, task failure, or raw zero.

## Repair and replacement

The minimal generic repair is to discover the container's effective runtime
UID when Harbor has no explicit `default_user`, bind that UID for the duration
of the upstream Codex run, and let Harbor's existing upload path correct file
ownership. Root and explicitly configured environments retain their existing
behavior.

The original attempt remains immutable. After focused tests and deployment,
the replacement job is
`tb3-sol-native-baseline-v1-risk-scorer-replay-k1-aws-x86-a2`.

## Preservation

- Regular files: 27
- Total bytes: 80,792
- Relative-path tree SHA256:
  `422aad3aedea798ee834af926f661b286bdcef0e39548755fa3d2d8a93778c72`
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-native-baseline-v1-risk-scorer-replay-k1-aws-x86-a`
