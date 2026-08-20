# TB3 bun native local attempt A

## Scope

- Task: `terminal-bench/bun-sourcemap-leak`
- Job: `tb3-sol-native-baseline-v1-bun-sourcemap-leak-k1-local-a`
- Agent: `codex-auth-no-session-baseline-v1`
- Model: GPT-5.6 Sol, max reasoning
- Codex: `0.148.0`
- Platform: local ARM64 Docker
- Sampling: raw k=1, standard timeout, no retries, no upload

## Outcome

This attempt has no raw reward and is protocol-invalid. The agent phase
completed, but the verifier environment image failed to build when a public
package download timed out. This is an infrastructure/environment-build owner,
not evidence about task correctness, model capability, StateM gain, or a
hardware ceiling.

- Completed trials: 1
- Errored trials: 1
- Error bucket: verifier environment-build network timeout
- Raw reward: none
- Cost: `$1.841766`
- Input/cache/output tokens: `1,129,542 / 1,066,752 / 33,148`
- ATIF: real `ATIF-v1.5`, 40 steps
- Raw-session directories: 0

The failure does not consume the task's two-attempt development progress budget.
It remains an immutable failed direct attempt in the fresh ledger. A replacement
direct cell uses a new job identity; the StateM half stays held until a valid
replacement direct result exists.

## Preservation

- Source and backup regular files: `22 / 22`
- Source and backup bytes: `407,257 / 407,257`
- Deterministic relative-path tree SHA256:
  `5c086725c09916800cbafe2ca6c5cc4792499824cf8595bca1b93f1c8146d3aa`
- Backup:
  `.statem/benchmarks/backups/tb3-sol-native-baseline-v1-bun-sourcemap-leak-k1-local-a`
- launchd label unloaded; experiment containers absent.
