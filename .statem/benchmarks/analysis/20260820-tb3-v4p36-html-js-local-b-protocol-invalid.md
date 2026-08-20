# TB3 HTML/JS v4p36 local lifecycle result

## Cell

- Job: `tb3-sol-evidence-v4p36-html-js-lifecycle-k1-local-b`
- Role: adapted extended-timeout lifecycle diagnostic; never score eligible
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p36-exp`
- Configuration: local ARM64 CPU, timeout multiplier 2.0, no retries, no upload

## Result

- Raw reward: unavailable
- Reward validity: invalid because verifier handoff was never reached
- Protocol validity: invalid
- Terminal error: StateM ended in `falsify`, not `handoff`
- API cost: **$0.311175**
- Input / cached / output tokens: 418,695 / 407,040 / 1,646
- ATIF: v1.5, 199 steps
- Codex: 0.148.0
- Source manifest: 35 files,
  `d4f1995d67683b336b79bb03a7906070c44fdd10c58b1307c3fc6291b70e6c4d`
- Raw-session files: 0

## Attribution

The candidate, immutable snapshot, candidate-blind preflight evidence, and
candidate-bound acceptance replay were all present. The transition into
`falsify` then ran four host in-hook commands. Review-open and context-view
succeeded, while falsifier-task rejected the canonical preflight receipt and
TeamRun initialization consequently had no task file. Four same-context resumes
made no durable progress, and verifier execution never began.

The receipt producer and proposal-binding gate use kind
`plan_preflight_evidence`; three downstream review consumers still required the
obsolete kind `preflight_evidence`. This is a host-owned mechanical schema
failure, not task capability evidence and not a raw zero. The same failure was
reproduced independently by the x86 risk sentinel.

The generic v4p37 repair uses the producer's canonical kind across falsifier
initialization, acceptance-obligation adjudication, and promotion. It does not
change semantic evidence, reviewer authority, task contracts, or recovery
routing.

## Preservation

- Source and local backup regular files: 63
- Source and local backup bytes: 2,645,814
- Deterministic relative-path tree SHA256, both copies:
  `ca6ecd4679a8c4d5eb44e4d44eb6e07f8a16e6a544f0d58f812114d835766d4e`
- Exact launchd label unloaded; experiment containers absent
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p36-html-js-lifecycle-k1-local-b`
