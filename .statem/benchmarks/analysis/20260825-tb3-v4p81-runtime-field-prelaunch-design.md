# TB3 v4p81 runtime field prelaunch design

## Observed gap

KV live surgery declares public artifacts with `service = "loadgen"`. Harbor
0.13.1 models only `source`, `destination`, and `exclude`, silently discards the
service owner, and then attempts collection from the wrong container. Daytona
and AWS Docker reproduced the same missing-artifact boundary after full solver
runs.

## Generic repair

Pinned local tasks now receive a host-side prelaunch receipt that compares every
top-level artifact declaration field with the installed Harbor
`ArtifactConfig.model_fields`. Unsupported fields reject before auth or an
environment starts. The check is enabled by default for pinned datasets and is
independent of the optional family route check.

The receipt is strict, hash-bound to `task.toml`, records runtime identity and
supported, declared, and unsupported fields, and is written atomically. It
contains no task answer, verifier result, credential, or solver advice. When a
newer Harbor runtime models `service`, the same task is admitted without a task
rule.

## Validation

- service-scoped artifact rejects against the Harbor 0.13.1 field set;
- the same declaration admits when `service` is modeled;
- legacy string artifacts remain compatible;
- unknown or tampered receipt fields reject;
- CLI rejection occurs before auth or environment startup;
- 37 TB3 focused tests pass;
- the hyper runbook remains strict-valid.

The exact AWS prelaunch against Harbor 0.13.1 rejected KV's unsupported
`service` field before Harbor startup and left zero experiment containers. The
bounded receipt is preserved at
`.statem/benchmarks/backups/prelaunch-receipts/v4p81-kv-runtime-fields.json`;
remote and local SHA256 are both
`397f56cc84f853df79e3070d6d2c0e9499018f4ed9b35dc1100ad6f50ec1e1ed`.

KV must not be rerun until a compatible Harbor build makes this prelaunch check
admit. This closes an infrastructure diagnostic loop; it does not promote a
task, subfamily, or family practice.
