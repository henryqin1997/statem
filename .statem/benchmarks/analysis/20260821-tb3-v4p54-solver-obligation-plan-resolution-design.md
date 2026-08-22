# TB3 v4p54 Solver Obligation And Plan Resolution Design

## Status

- Implemented and tested only in the isolated source tree
  `/private/tmp/statem-v4p54-isolated.6E6g0J`.
- Reproduced as local Git commit
  `171c6c9294c779208d618fc03b1ba1fb94446d21` on isolated branch
  `codex/tb3-v4p54-solver-obligations-20260821`, with parent v4p53 commit
  `11e8d9e5e438960cbff657b6529c23478d40242a`.
- Not deployed and not used by any active raw or adapted benchmark cell.
- The active v4p52/v4p53 source tree remained frozen while HTML/JS, Next.js,
  and Intrastat were running.
- This is a control ablation design, not reward evidence or a pass-rate estimate.

## Single Experimental Variable

v4p54 closes the gap between solver-visible practice and independent review
without adding a free-running semantic orchestrator in the same ablation.

1. The host projects mandatory common practices, every primary reviewer-profile
   check, and one compact scope obligation for each secondary profile.
2. The solver plan covers every projected obligation exactly once through a
   bounded `obligation_coverage` mapping.
3. Reviewer-private counterexample priorities, adversarial probe selection, and
   verdict calibration remain outside the solver projection.
4. A candidate-blind `revise_plan` verdict produces immutable issue ids. The
   solver must submit a revised plan that changes each named plan section and
   resolves every issue before its proposal can bind and leave solve.
5. A `ready` verdict receives a host-owned `not_required` resolution. Stale
   drafts from prior entries are ignored.
6. Final falsification remains independent. The change guarantees enforcement
   of an observed plan-review gap, not complete semantic defect detection.

The full semantic orchestrator remains a later, separate variable. Current
StateM deterministic lifecycle, identity, deadline, artifact, and promotion
gates retain transition authority.

## Compatibility

- v4p54 has a distinct adapter identity and runbook.
- Existing plan, preflight task, and proposal functions retain their old output
  shape when solver obligations and preflight resolution are not supplied.
- v4p53 behavior is therefore not silently upgraded.

## Validation

- Strict v4p54 runbook validation: passed.
- New focused tests: 5 passed.
- Promotion, preflight repair, recovering develop, failure closure, and new
  v4p54 focused group in the Git-isolated tree: 140 passed.
- Broader committed experimental test discovery after restoring its ignored
  reviewer-practice decision fixture: 164 passed.
- A full 252-test discovery was also attempted. It had one error and six
  failures because the isolated `git archive` intentionally lacked Git metadata,
  an uncommitted TeamRun example directory, and the example progress-file
  layout expected by those tests. These are isolation-fixture failures and are
  not counted as passing validation.

## Backup

- Archive:
  `.statem/benchmarks/source-snapshots/20260821-v4p54-solver-obligation-preflight-resolution-isolated.tar.gz`
- Bytes: `59400`
- Archive SHA256:
  `966ad89f6ccea4bbffec1e016bac8a0a2a71b49d4cb2c3114838b3af089247bb`
- Four-file deterministic relative-path/content SHA256:
  `d53ce6a0b60fae4b9d7ba8b8e7037ade96827e120b3932a30fbddefef573cdd6`
- Dependency-complete Git bundle:
  `.statem/benchmarks/source-snapshots/20260821-v4p54-solver-obligations.bundle`
- Bundle bytes: `2213821`
- Bundle SHA256:
  `c639ef89881c535e5de4b58d7c8430a7c126920a31938b21f972c165c76c8b12`
- `git bundle verify`: passed; the bundle records complete history and the
  exact isolated branch ref.

## Admission Gate

Do not deploy v4p54 while an existing source-manifest-bound job is active.
After the active lanes are archived, merge the isolated increment onto the
then-current source and rerun the dependency-complete suite.

The first live ablation is predeclared as a same-platform adapted pair on
`terminal-bench/mvcc-lsm-compaction`: one frozen v4p53 baseline followed by one
v4p54 candidate, both raw k=1 with identical model, reasoning, timeout, retry,
and no-upload settings. MVCC is a relatively low-cost, previously raw-positive
sentinel whose historical preflight outcome was `revise_plan`; it tests whether
the new hard plan-resolution closure preserves reward while changing only the
solver-obligation and preflight-resolution variable. It is adapted regression
evidence, not fresh score evidence and not a pass-rate estimate.

The frozen local v4p53 baseline launcher is
`.statem/benchmarks/launch/run_tb3_evidence_v4p53_mvcc_obligation_baseline_k1_local_arm_a.sh`
with SHA256
`2e504f9bd861369623ab9bed4f536f8623467f0df4725eabe0924426d2221127`.
Its launchd definition is
`.statem/benchmarks/launch/com.statem.tb3.mvcc.v4p53.baseline.plist` with
SHA256
`866bf967b89e08a45438d44e05feb071cabfd6f34c33a700f140874b73161ef5`.
Both passed syntax validation before launch. The cell uses the public
14,400-second agent deadline, timeout multiplier 1.0, one attempt, no retries,
and no upload. Do not load it until the active local HTML/JS job, Harbor
processes, reviewers, and container have exited and its artifacts are backed
up and checksum verified.

The frozen v4p54 candidate launcher is
`.statem/benchmarks/launch/run_tb3_evidence_v4p54_mvcc_obligation_candidate_k1_local_arm_a.sh`
with SHA256
`c61731530c10a47a400681edcdfe75e23b7e5e0c2bf521b45fa811a407938bbb`.
Its launchd definition is
`.statem/benchmarks/launch/com.statem.tb3.mvcc.v4p54.candidate.plist` with
SHA256
`53f7be345b953042f7c846d0f8e6e76fab5cc83a177525ef743a8b51a487c411`.
Both passed syntax validation. A direct launcher diff confirms that the only
baseline/candidate differences are job name, adapter identity, and adapter
import class. Do not load the candidate until the baseline is fully archived,
v4p54 is merged, dependency-complete tests pass, and the candidate import and
strict runbook validation succeed in the live workspace.

The deterministic `ready -> not_required` path remains covered by focused
tests. Do not repeatedly sample live tasks merely to force a `ready` verdict.
A live ready-path observation may be added only when it occurs naturally in a
task selected before the v4p54 result, with its selection basis recorded first.
This avoids outcome-conditioned task selection and unnecessary API spend.

Measure raw reward, protocol validity, solver time, plan-revision frequency,
false-positive revisions, final-review catches, API cost, and wall time
separately. Do not promote v4p54 into fresh score lanes if the matched sentinel
regresses reward, strands lifecycle state, or increases false-positive
revision without compensating evidence gain.
