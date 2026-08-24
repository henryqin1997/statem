# TB3 v4p71 ERP local ARM infrastructure result

## Classification

- Task: `terminal-bench/erp-procurement-planning`
- Cell: intended adapted compact-practice development
- Reward validity: invalid; no verifier reward was produced
- Protocol validity: invalid; the agent never started
- Model usage and API cost: zero

The local Docker build timed out while resolving metadata for the public
`odoo:19` base image. A bounded pre-pull also made no layer progress, so the
local lane was stopped without a model call. Together with the repeated
Daytona dependency-download failures, ERP has no currently healthy execution
lane.

## Routing audit

The frozen visible-instruction selector chooses
`structured_transformation_compact`, not the preregistered
`stateful_lifecycle_compact`. The adapter would have failed closed before a
model call had setup succeeded. Therefore the proposed ERP cell was also
design-invalid and must not be described as evidence for either practice.

The correction is not to bypass the selector. ERP is parked until its route is
preregistered against the exact visible selector and a healthy environment is
available. The next adapted cell moves to another task with an exact selected
practice and an existing public validation delta.

## Preservation

- Source and backup regular files: 9 each
- Source and backup bytes: 49,277 each
- Deterministic relative-path/content tree SHA-256, both copies:
  `dbd25af92616fa15526e2d20758701f92b9427bc9bf3db0862265b77953f740b`
- `rsync -nrc --delete`: empty
