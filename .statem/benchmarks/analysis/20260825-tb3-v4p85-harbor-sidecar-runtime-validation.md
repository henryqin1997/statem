# TB3 v4p85 Harbor sidecar runtime validation

## Runtime

- Upstream commit: `6ecebe4ae9910ee0b28a2e6e8fa30934c0b41dfa`.
- Installed package: Harbor `0.22.0` in an isolated AWS virtual environment.
- Artifact fields: `destination`, `exclude`, `service`, `source`.
- Frozen Harbor `0.13.1` and all completed jobs were left unchanged.

## Validation

- Payments task-field prelaunch: admit, no auth/environment/model access.
- StateM harness dry-run: passed with zero containers.
- Generated agent config parsed by the new Harbor CLI; a deliberate no-match
  filter enumerated all 74 tasks and exited before environment startup.
- Upstream sidecar-artifacts Oracle smoke: raw `1.0`, protocol valid, zero
  errors/retries, two sidecar artifacts collected successfully, no remaining
  containers.
- Smoke backup: 14 files, 10,317 bytes, deterministic tree SHA256
  `ad925386b1c72aca9939711f48f8c9c6f080e04e0a9e238c220494e8b1763ad3`;
  checksum dry-run empty.
- Payments prelaunch receipt file SHA256:
  `a54c4809de5fa5064f5d5bb68410360d6cb353e47461518f63ee6b632e92f80b`.

## Decision

Admit exactly one Payments fresh direct cell under this pinned runtime. The
runtime change is infrastructure, not a family practice. Do not reuse it for a
different task until that task passes its own runtime-field preflight and the
Payments cell closes without a runtime violation.
