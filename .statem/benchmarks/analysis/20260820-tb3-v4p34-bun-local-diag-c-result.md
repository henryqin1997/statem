# TB3 v4p34 Bun Extended Diagnostic Result

## Result

- Job: `tb3-sol-evidence-v4p34-bun-sourcemap-leak-k1-local-diag-c`
- Task: `terminal-bench/bun-sourcemap-leak`
- Role: adapted extended-time lifecycle diagnostic; never score eligible
- Raw reward: **0.0**
- Reward validity: valid observation under extended timeout, excluded from score
- Protocol validity: valid terminal handoff
- Errors / retries: 0 / 0
- Model: GPT-5.6 Sol, max reasoning
- Codex: 0.148.0
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p34-exp`
- ATIF: v1.5, 133 steps
- Input / cached / output tokens: 10,518,007 / 10,240,000 / 67,541
- API cost: **$8.536265**
- Wall / agent time: 2,209.038 / 2,167.213 seconds
- Raw-session directories: 0

## Protocol Evidence

- Final StateM state: `handoff`
- Route: `solve -> falsify -> revise -> falsify -> quarantine -> final_replay -> handoff`
- Family: `structured-transformation`
- Primary reviewer profile: `parsing-transformation`
- Secondary profiles: `security-protocols`, `stateful-systems`
- Source manifest: 35 files,
  `c6ddf782bd8695e1c30dfee371e2a21d0237f3aff5bc785a8943c6cc3a557973`
- Candidate quarantine application receipt: verified with matching expected and
  observed artifact identities
- Final promotion decision: revise/reject with no blocking regression and no
  hard-contract provenance gap
- Final replay decision: handoff; another full cycle was not deadline-feasible

The run closed the earlier protocol failure: it did not terminate in `revise`
and it produced a valid raw result. The final review also narrowed the remaining
failure to an implementation defect and recorded a new append-only validation
delta. However, the new v4p34 in-cycle revision-reserve route was not itself
exercised: the second review exhausted the review budget, so quarantine was
mandatory, and the existing full-cycle deadline gate selected handoff with
1,459 seconds remaining versus a 2,100-second retry reserve.

This is therefore positive lifecycle-closure evidence but not score gain and
not causal validation of the new revision-reserve branch. Bun is parked until a
new generic candidate-sampling/ranking control, cheaper discriminator, or
materially narrower owner appears from another task.

## Preservation

- Source and backup regular files: 146
- Source and backup bytes: 4,393,774
- Deterministic relative-path tree SHA256, both copies:
  `ee5cf8b0ad0fb94d496e75b7d9c2d65b42e565690b0313cce4c1b162a3e8ba2d`
- Exact launchd label unloaded after completion
- Experiment container absent after completion
