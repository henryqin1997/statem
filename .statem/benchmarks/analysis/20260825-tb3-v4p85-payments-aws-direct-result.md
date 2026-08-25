# TB3 v4p85 Payments isolated-runtime direct result

## Result

- Evidence class: fresh direct runtime replacement.
- Raw reward: `1.0`; reward and protocol valid.
- Errors / retries: `0 / 0`.
- Model / agent: GPT-5.6 Sol max, direct baseline-v2, Codex `0.149.1`.
- Runtime: isolated Harbor `0.22.0` at upstream commit
  `6ecebe4ae9910ee0b28a2e6e8fa30934c0b41dfa`; frozen Harbor `0.13.1`
  remained untouched.
- Cost: `$3.820958`.
- Tokens: 4,735,925 input; 4,566,784 cached; 65,884 output.
- Wall / agent time: about 40.6 / 35.5 minutes.
- ATIF: `ATIF-v1.7`, 78 steps; raw-session paths absent.
- Public artifacts: application source and the Kafka service snapshot were
  collected successfully; the declared conventional log directory was empty.

Harbor `0.13.1` rejected this task before launch because its artifact schema
did not model the declared sidecar `service` field. The isolated runtime first
passed exact-field preflight, StateM dry-run, and the upstream sidecar Oracle
smoke. This fresh task then completed its solver, service-artifact transfer,
and verifier lifecycle with raw one. The earlier rejection was therefore
runtime compatibility ownership, not task failure.

## Routing decision

Freeze Payments on direct solve. Do not create a StateM arm or extract a task
practice from a solution that already passes. Keep runtime selection behind
the global exact-field prelaunch gate and a per-task compatibility receipt;
this one result does not authorize blanket migration of other tasks.

## Preservation

- Remote/local regular files: `22 / 22`.
- Remote/local bytes: `73,469,084 / 73,469,084`.
- Deterministic relative-path/content tree SHA256:
  `98f1782a937e3602c539521165d8e2190381d726e2119936b0f96f9e9d74c9ae`.
- Remote-to-local checksum dry-run: empty.
- Runner, Harbor, verifier, tmux session, and task containers: exited.

Backup:
`.statem/benchmarks/backups/tb3-sol-native-baseline-v2-payments-v4p85-harbor-sidecar-k1-aws-x86-a`
