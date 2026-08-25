# TB3 v4p84 Payments runtime-field rejection

## Result

- Evidence class: fresh direct prelaunch calibration; no trial started.
- Decision: reject before auth, environment startup, or model execution.
- Reason: the pinned task declares a sidecar `service` artifact field that
  Harbor `0.13.1` does not model.
- Reward / protocol: no reward; no benchmark protocol claim.
- Model cost / containers: zero / zero.
- Remote/local receipt file SHA256:
  `f4b7f05c518382435ef670f1275fec7c44fb874cdbf04d96ad4730e6ac376905`.
- Content-addressed receipt SHA256:
  `40c87823385d1a7dda7f16e9e6300c0e900f6023662d813df33029fd27f66f60`.

The host gate behaved as intended and prevented another full solve whose
sidecar evidence could not be transferred to the verifier. This is a generic
runtime compatibility boundary, not a payments task-control observation.

## Next boundary

Current Harbor `main` models sidecar `service` artifacts, but the feature is
still listed as unreleased and accompanies artifact-layout and lifecycle-event
breaking changes. Test a pinned upstream commit in an isolated runtime first;
do not weaken the field gate or upgrade the frozen evaluation environment in
place.

Primary upstream references:

- <https://github.com/harbor-framework/harbor/blob/main/src/harbor/models/task/config.py>
- <https://github.com/harbor-framework/harbor/blob/main/CHANGELOG.md>

Receipt:
`.statem/benchmarks/backups/prelaunch-receipts/v4p84-payments-runtime-fields.json`
