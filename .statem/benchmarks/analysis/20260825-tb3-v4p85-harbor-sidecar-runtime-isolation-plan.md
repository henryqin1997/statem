# TB3 v4p85 Harbor sidecar runtime isolation plan

## Goal

Validate the generic runtime boundary exposed by KV and Payments without
modifying the frozen Harbor `0.13.1` environment or launching a model.

## Frozen increment

- Upstream: `harbor-framework/harbor` main commit
  `6ecebe4ae9910ee0b28a2e6e8fa30934c0b41dfa`.
- Installation: dedicated AWS virtual environment outside every StateM source
  and benchmark job directory.
- Expected schema delta: `ArtifactConfig` includes sidecar `service`.
- No credential, task prompt, verifier, agent, or container is accessed during
  setup.

## Admission sequence

1. Install the exact Harbor commit in the isolated environment.
2. Verify package identity and the exact artifact-field schema.
3. Re-run the content-addressed Payments task-field prelaunch against that
   runtime; it must admit without weakening the gate.
4. Run focused harness compatibility tests and dry-run validation.
5. Only then freeze a new direct cell. Keep artifact-layout and lifecycle-event
   changes inside this runtime generation.

Any failed import, missing `service` field, receipt mismatch, harness test
failure, or dry-run failure blocks a live task launch.

## Outcome

All five admission stages passed under isolated Harbor `0.22.0`. The upstream
sidecar Oracle smoke was reward- and protocol-valid with successful service
artifact collection. Exactly one Payments fresh direct runtime-replacement cell
is admitted; broader runtime reuse remains unapproved.
