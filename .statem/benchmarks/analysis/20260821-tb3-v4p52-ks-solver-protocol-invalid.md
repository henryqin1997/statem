# TB3 v4p52 KS Solver Protocol-Invalid Result

## Result

- Job: `tb3-sol-evidence-v4p52-ks-solver-matched-k1-aws-x86-b`
- Task: `terminal-bench/ks-solver-cpp`
- Cell role: adapted matched development cell
- Raw reward: **not available**
- Reward validity: false
- Protocol validity: false
- Final StateM state: `solve`, expected `handoff`
- Verifier execution: none
- Error / retries: RuntimeError / 0
- Model: GPT-5.6 Sol, max reasoning
- Codex: 0.148.0
- Input / cached / output tokens: 1,361,431 / 1,340,160 / 5,789
- API cost: **$0.950105**
- ATIF: v1.5, 280 steps
- Source manifest: 36 files, SHA256
  `fb2cf1a10c86496cd40a079306856333708b2cf8503d8c28dab0d61d120ebc4f`
- Raw-session paths: 0

This cell must not be counted as raw zero. The benchmark verifier never ran.

## Attribution

The official task deadline receipt used the task's 14,400-second timeout and
was not the limiting condition. Cycle one completed two reviews, routed a
repairable acceptance-plan gap to quarantine after review-budget exhaustion,
and performed exact-candidate replay. The replay classified the failure owner
as `test_planner`: the acceptance population had already influenced candidate
selection and therefore could not independently close the quantitative claim.

The retry correctly requested a frozen external population, but v4p52 did not
bind that validation delta to a targeted candidate-blind requirement. Cycle two
opened and remained in `solve`; two transfers to `falsify` were blocked and the
entry-scoped stop hook consumed its continuation budget without closing the
missing prerequisite. The agent collection boundary then rejected the non-
handoff final state.

The primary failure is therefore lifecycle/protocol progress closure after a
test-planner-owned validation delta, not solver correctness, hardware, or the
official task timeout. It supports the later targeted-validation and explicit
solver-obligation controls, but cannot be rewritten as v4p53/v4p54 evidence.

## Preservation

- Remote / local regular files: 108 / 108
- Remote / local bytes: 7,350,433 / 7,350,433
- Deterministic relative-path/content tree SHA256, both copies:
  `a06552fa7c115821de16295d58914ca46535bbcd61e29ba451d7dc77cfac25b3`
- `rsync -nrc --delete`: empty
- Remote runner and task container: absent
