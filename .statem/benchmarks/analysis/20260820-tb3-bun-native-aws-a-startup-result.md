# TB3 bun native AWS attempt A

## Outcome

Job `tb3-sol-native-baseline-v1-bun-sourcemap-leak-k1-aws-x86-a` exited before
creating a trial because the native baseline harness module had not been
deployed on the remote host. It has no task execution, raw reward, tokens, or
API cost and is startup/protocol-invalid. It is not a model, task, StateM,
hardware, or benchmark result.

The incomplete import check was an orchestration error: the earlier remote
validation command did not surface its nonzero exit status. The corrected
procedure deploys only the already-tested native harness, runs its two focused
tests, requires an explicit success marker and exit code zero, then launches a
replacement with a new job identity. Deploying this independent harness does
not change the active v4p33 StateM source manifest.

## Preservation

- Remote/local regular files: `5 / 5`
- Remote/local bytes: `6,844 / 6,844`
- Deterministic relative-path tree SHA256:
  `69b1098634b17c5c1f250951755b79df40bf66f87e82f433b0660ba635105cac`
- Backup:
  `.statem/benchmarks/backups/tb3-sol-native-baseline-v1-bun-sourcemap-leak-k1-aws-x86-a`
- No task container or raw-session directory was created.
