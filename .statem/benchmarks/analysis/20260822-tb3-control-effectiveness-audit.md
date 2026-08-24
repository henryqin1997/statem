# TB3 extracted-control effectiveness audit

## Evidence standard

Passing a development task does not by itself validate an extracted control.
This audit keeps four evidence axes separate:

1. **Mechanism**: focused tests and bound receipts prove that the intended
   route, role, provider transaction, or gate actually executed.
2. **Adapted outcome**: a task already used for diagnosis produces a valid raw
   result after the control change.
3. **Negative transfer**: a previously passing task remains reward-valid and
   protocol-valid under the new control.
4. **Fresh generalization**: a frozen control improves an unseen matched raw
   pair. Only this axis supports the phase-one score target.

## Positive adapted evidence

| Task | Before/after evidence | Mechanism evidence | Negative-transfer status | Fresh-score use | Verdict |
|---|---|---|---|---|---|
| interleaved-vigenere | v4p29 raw 0, v4p30 raw 1 | candidate-blind acceptance and information-gain receipts valid | not independently isolated because both controls changed together | excluded, adapted | useful same-task result; causal component not isolated |
| embedding-drift-monitor | early Develop cells raw 0 after broken behavior became hard contract; v4p28 raw 1 after repair-aware authority | hard-versus-defeasible seal, paired evidence, candidate replay, and handoff valid | no independent later sentinel | excluded, adapted | strong authority-repair evidence, not cross-task proof |
| vf2-speedup-networkx | v4p16 raw 0 at 59/60; v4p19 and v4p20 raw 1 | fixed population, consumer-path, lease, evidence packet, and replay receipts valid | repeated raw 1 across two later variants | excluded, adapted | strong same-task and repeat evidence |
| mvcc-lsm-compaction | raw 1 in v4p14 and v4p53-v4p57; v4p58 raw 0 | obligation projection, candidate replay, promotion, provider activation, and submission identity receipts valid | v4p58 broke the prior passing sentinel after accepting a different finite-population-fit candidate | excluded, adapted | strong sentinel; v4p58 rejected for real negative transfer |
| risk-scorer-replay | raw 1 in v4p41 and v4p51 | failure closure, candidate replay, and handoff valid | reward preserved, but false-heavy retry and cost/wall overhead observed | excluded, sentinel | functional safety positive; efficiency regression remains |
| session-window-debug | v4p21 raw 1, later v4p31 raw 0 | lifecycle and receipt protocol valid in the zero cell | failed to preserve reward in the later sentinel | excluded, adapted | unstable; control not accepted as generally effective |

## Negative and non-converting evidence

| Evidence class | Tasks | What is established | What is not established |
|---|---|---|---|
| valid fresh 0 to 0 | production-planning, cargo-flight-dispatch, foodstuff-beta-activity, distributed-dedup, pretrain-shard-corruption | frozen controls completed standard raw evaluation without reward gain | no cross-task score uplift; task root cause is not fully identified |
| valid adapted raw 0 | lake-temp-glm, CAD variants, ERP/Intrastat variants, earlier interleaved and session sentinels | environment and protocol can be separated from semantic failure | reviewer findings are not automatically the complete task root cause |
| protocol-invalid | Bun sourcemap, data anonymization, HTML/JS, KS solver, FreeCAD impeller, RS archive, VBA matched | lifecycle, receipt, workspace, provider, or progress owner is observable | no benchmark reward and no semantic success/failure claim |
| direct-only calibration | formal crypto, ontology, GSEA, medical claims, freight dispatch, scientific specialist and CAD calibrations | baseline raw difficulty and hardware feasibility | no StateM improvement because no eligible frozen matched conversion exists |

## Submission-gate regression pair

The v4p56 gate is validated against complete archived receipt sets and two live
adapted executions:

- Pretrain contains structured negative evidence and failed replay. The gate
  selects baseline and requires verified restore before handoff.
- The synthetic MVCC receipt pair contains only advisory uncertainty after
  review-budget exhaustion and passed candidate-bound public replay. The gate
  preserves candidate handoff while still denying promotion.
- Live MVCC completed raw 1 with a mechanically valid promote decision,
  candidate-bound replay, verified provider activation, and exact candidate
  submission identity.
- Live Music completed raw 0 after candidate replay passed but its review
  receipt was mechanically invalid. The gate made the candidate ineligible,
  selected baseline, and verified an exact transactional restore before
  handoff. This validates conservative fallback behavior, not task success.

The gate and lifecycle pass 112 focused tests, including an exact filesystem
restore transaction. The live pair validates both candidate submission and
baseline restoration and rejects blanket rollback. One receipt-semantic defect
remains outside the v4p56 eligibility decision: a valid promote receipt reported
`candidate_revision_required: true`. It is fixed and covered by 113 focused
tests in isolated v4p57. The live v4p57 MVCC sentinel preserved raw `1.0`,
protocol validity, candidate submission, and recorded the corrected field as
false on a promote decision.
Music's `fallback_required: false` is not a second behavior defect: focused
lifecycle tests define that field as pending restore work, so it becomes false
after a verified restore. The name is easy to misread; completed fallback is
proven by the selected baseline, required restore mode, verified provider
application, and `baseline_fallback_verified` reason.

The later v4p58 terminal-provider experiment is not admitted. Its SGLang cell
remained protocol-invalid in quarantine and its MVCC sentinel regressed from
v4p57 raw `1.0` to v4p58 raw `0.0` despite a mechanically valid promoted
candidate handoff. Public-artifact attribution showed that finite acceptance
evidence had been allowed to close a wider declared claim. This is the negative
case for the unstacked v4p59 evidence-scope gate; it is not fresh uplift.

The first unstacked v4p59 implementation also remains unadmitted. A replay of
the real v4p58 MVCC preflight showed that merely relabeling all requirements as
bounded could pass while preserving their named uncovered regions. v4p59 was
rejected without a live trial. v4p60 adds machine-checked boundary closure and
blocks the legacy, under-scoped bounded, and contradictory-complete forms of
that archived receipt, but a raw-`1.0` v4p57 pre-audit showed that it would also
force all six bounded requirements with declared boundary regions into
generalization. v4p60 was therefore rejected before live execution for
false-heavy negative-transfer risk.

v4p61 separates material gaps inside a claim from contract-justified boundaries
outside it. The host requires every scope exclusion to be dispositioned by an
independent reviewer against sealed-contract or public-surface authority.
Missing evidence is repairably normalized to unresolved and routes to revise;
material/unresolved exclusions block; fully audited out-of-scope boundaries do
not force generalization. Focused tests cover each branch and the complete
source suite passes under the existing sparse-worktree exclusions.

The live v4p61 MVCC sentinel preserved raw `1.0`, protocol validity, exact
candidate promotion/submission identity, and a complete v4 assessment. It used
five closed bounded requirements and one generalization requirement whose four
uncovered regions were independently dispositioned. Every `scope_exclusions`
list was empty, so the new positive exclusion branch remains fixture-tested
only. Relative to the earlier v4p57 raw-one sentinel, recorded cost rose 63.9%,
wall time 84.0%, input tokens 79.3%, and ATIF steps 40.5%. Platform and sampling
differences prevent pure causal attribution, but this is not sufficient to
admit the heavy global path. v4p61 remains mechanism evidence and supplies no
fresh uplift.

## v4p62 thin reset

v4p62 restores the Terminal-Bench 2.1 thin pattern. Its default runbook is 86
lines rather than v4p61's 791, its live source manifest has 10 files rather
than 37, and a visible-instruction selector can activate at most one compact
family practice. Detailed checks remain reviewer-only catalog data; an
independent reviewer runbook and the new nested-runbook core remain dormant
without comparative evidence that inline review is insufficient.

The adapted MVCC negative-transfer sentinel preserved raw `1.0` and protocol-
valid `handoff` for `$1.0312304` in about 12m42s. Its actual path was
`solve -> verify -> solve -> verify -> self_review -> handoff`, validating a
local Revise without quarantine or rollback. Against v4p61's descriptive
evidence, cost fell 91.1% and wall time 73.6%; platform, Codex version, and
sampling differences prevent pure causal attribution.

The preregistered fresh `batched-eval-parity` k1 pair then completed direct
raw `0.0` versus StateM raw `1.0`, with both reward-valid and protocol-valid.
Both arms used GPT-5.6 Sol max, Codex 0.149.0, local ARM64 Docker, standard
timeouts, no retries, and no upload. The StateM arm selected exactly the
`algorithm-performance` compact practice, ended in `handoff`, cost `$3.297902`
versus direct `$3.723238`, and used 62 ATIF steps versus 72. This is the first
fresh positive matched observation in the ledger. It admits the existing high-
precision algorithm-performance compact route for another frozen comparison;
it does not justify broader triggers, global detailed reviewer context, or a
pass@5 uplift claim.

## Current score conclusion

Eight score-eligible fresh k1 pairs are complete. Seven are raw 0 to 0 and the
v4p62 `batched-eval-parity` pair is direct 0 to StateM 1. VBA is protocol-
invalid. The observed fresh raw delta is therefore `+1` trial, equivalent to
`0.27027` points of raw accounting over the 370-trial matrix. This is k1 triage,
not an estimated or verified pass-rate gain, so the 15-point target remains
unsupported. Adapted raw ones remain mechanism evidence and never enter the
fresh numerator.

## Active frozen generalization cells

The completed-score conclusion above is unchanged while these cells run:

- `sglang-qwen-burst`: fresh direct raw `0`; frozen v4p57 StateM arm completed
  protocol-invalid in final `quarantine`, before verifier reward. Candidate-
  blind routing selected `structured-transformation` with
  `parsing-transformation` primary and `performance-resources` secondary. The
  metadata-prior mismatch is a measured route outcome, not the protocol defect.
  Entry-time candidate application was verified, but the live artifact drifted
  before transfer-time identity verification. This exposed a generic terminal-
  provider snapshot/live TOCTOU gap; the pair contributes no reward delta.
  The adapted v4p58 repair check also ended protocol-invalid in `quarantine`,
  so the terminal reassertion control is rejected rather than inherited by
  v4p59.
- `sound-change-cascade`: fresh direct raw `0`; frozen v4p57 StateM raw `0`,
  protocol-valid handoff, exact promoted candidate submission, matched delta
  zero. Candidate-blind routing selected `structured-transformation`, matching
  the predeclared prior. The control chain executed correctly, but the final
  reviewer allowed public training fit and bounded short-form evidence to
  satisfy a broader generalization obligation despite explicitly retained
  observationally equivalent orderings. This is a fresh generic
  evidence-role/support-scope counterexample, not uplift.
- `batched-eval-parity`: the heavy v4p61 launchers were retired unlaunched. A
  newly preregistered v4p62 thin pair completed direct raw `0.0` versus StateM
  raw `1.0` with valid protocol and backups. It is now completed fresh k1
  evidence, not an active cell and not a pass@5 estimate.

No active or unlaunched cell contributes reward before standard-timeout result,
protocol, receipt, ATIF, raw-session, and checksum-preservation audits finish.
The official mid-score portfolio is recorded separately and shifts future
allocation toward clean `2/5` through `4/5` CPU tasks rather than only the
lowest-score tail.

## v4p69 no-match and cloud cleanup evidence

The fresh HOF Daytona pair observed direct raw `0.0` and StateM raw `0.0`.
Direct was protocol-valid. StateM reached `handoff`, used the exact canonical
10-file manifest, and correctly recorded `selected=false`, `activated=false`,
`activation_reason=no_match`; however, one locally downloaded raw Codex session
remained after ATIF conversion, so the StateM arm is protocol-invalid and the
pair supplies no score evidence.

The StateM path ran solve/verify twice before self-review and handoff, taking
1791 seconds versus direct's 1340. Public submitted outputs differed only on
one of seven records, where the second attempt selected a different topology
and interpenetration hypothesis; both complete outputs scored zero. This is a
real bounded rebranch but lacks a public discriminator. One zero-to-zero pair
does not close the task, while further adapted rollout requires a new
falsifiable oracle or validation delta. Independently, no-match routing must be
made direct-like and local cloud sessions must be removed after ATIF conversion
before another fresh pair is admitted.
