# TB3 foodstuff beta activity v4p35 local lifecycle result

## Cell

- Job: `tb3-sol-evidence-v4p35-foodstuff-beta-activity-k1-local-c`
- Role: adapted obligation-closure development cell; never score eligible
- Model: GPT-5.6 Sol, max reasoning
- Agent: `ziheng-yaxin-statem-codex-evidence-develop-v4p35-exp`
- Configuration: local ARM64 CPU, standard 9,000-second timeout, no retries, no upload

## Result

- Raw reward: unavailable
- Reward validity: invalid because verifier handoff was never reached
- Protocol validity: invalid
- Terminal error: StateM ended in `falsify`, not `handoff`
- API cost: **$0.515696**
- Input / cached / output tokens: 811,144 / 800,512 / 2,076
- ATIF: v1.5, 140 steps
- Codex: 0.148.0
- Source manifest: 35 files,
  `008248e50f9bd3e262376b154e95c5ffd25651e1c38d5e8521088dfa51188bdc`
- Raw-session files: 0

## Attribution

The candidate-blind plan created six obligations split between adapter replay
and analytic review. The exact candidate-bound replay executed all four planned
public checks, passed them, covered its required strata, and bound the proposal,
preflight plan, and candidate snapshot. The lead then entered `falsify`, but no
review worker was launched and the host ended after only two same-context
resume attempts.

This is a host lifecycle failure, not a raw zero and not evidence that the
candidate was correct. The two-resume no-progress rule did not treat pre-seal
plan/reviewer drafts as progress and could terminate before a nonterminal node
closed. Production reproduced the same owner independently.

The generic v4p36 repair expands the bounded progress witness to candidate-blind
drafts, permits four consecutive unchanged resumes inside the existing hard
eight-resume/deadline bounds, and emits a bounded state/progress trace. Foodstuff
is parked until that generic repair is validated elsewhere; repeated adapted
runs cannot become final evidence.

## Preservation

- Source and local backup regular files: 68
- Source and local backup bytes: 1,993,106
- Deterministic relative-path tree SHA256, both copies:
  `d92bae16a2e730204c1dcc930c1368ce2dbec535689e0e68cfd3fee13be750ee`
- Exact launchd label unloaded; experiment containers absent
- Local backup:
  `.statem/benchmarks/backups/tb3-sol-evidence-v4p35-foodstuff-beta-activity-k1-local-c`
