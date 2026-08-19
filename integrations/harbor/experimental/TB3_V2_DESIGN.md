# Terminal-Bench 3 Experimental Control Log

This file records incremental, task-general control changes for the local
Terminal-Bench 3 development path. These controls are experimental and do not
change the default `StatemCodex` route.

## 2026-08-19: authority, evidence, and stage portfolio

### Contract authority and repair

The preflight reviewer now returns a bounded `contract_ledger` with four views:

- hard constraints supported by an allowed authority basis;
- defeasible claims from broken or stale implementation evidence;
- conflicts that need a discriminating public probe;
- repair implications that name scope, preserved abstraction, and verification.

The full authority practice remains reviewer-owned. The lead solver consumes
the compact ledger and uses only `incumbent`, `candidate`, and `final` as
artifact concepts. Adapter-owned baseline, quarantine, and rescue snapshots
remain transaction metadata.

### Mechanical pre-submit

`multirole_promotion_gate.py review-pre-submit` performs only mechanical work:

1. bind missing candidate, contract, context, protocol, and profile identities
   from trusted receipts;
2. canonicalize an unambiguous legacy `id` to `stage_id`;
3. reject conflicting identities or conflicting field names;
4. preserve every semantic reviewer field unchanged.

The canonical receipt is hash-bound and consumed by `decide`. Mechanical
repair does not spend semantic review budget and cannot authorize promotion.

### Hard quantitative acceptance gaps

The falsifier may emit `hard_contract_gaps` only for an explicit quantitative
acceptance claim. Each gap binds contract authority, exploration or acceptance
role, population id, observed evidence, required independent evidence, and a
bounded repair action. Generic concern or incomplete prose is not a hard gap.

A valid unresolved gap blocks promotion. If review budget is exhausted, the
candidate is quarantined for exact replay rather than rolled back. A passing
correctness replay still opens the next bounded recovery cycle unless final
replay binds fresh independent evidence that resolves every hard gap. This
closes the VF2 failure mode where an adaptive population exposed a threshold
miss but a partial public replay caused premature handoff.

### Exploration and acceptance

Samples that affect implementation become exploration evidence permanently.
Final acceptance must use a population fixed before candidate adaptation and
kept untouched until the candidate is bound. A failed acceptance population can
feed the next cycle only after a fresh acceptance population is allocated.

The reviewer and recovery schemas now enforce evidence roles and population
identities for hard quantitative gaps. Provider-owned hidden population
allocation is not yet wired into the generic adapter; do not describe that part
as implemented until the provider can enumerate a task's public sample space
without task-specific logic.

### Stage portfolio v2 skeleton

`stage_portfolio_v2.py` provides the minimum protocol layer for future
multi-agent stage ranking:

- one to three dependency-ordered stages;
- at most two isolated challengers, and only for a high-risk stage;
- explicit inputs, outputs, invariants, mandatory checks, and resource budgets;
- deterministic eligibility screening before semantic ranking;
- an independent reviewer orders only the eligible set;
- the lead owns integration;
- a stage winner has no final promotion authority;
- untouched final replay remains mandatory.

The module intentionally does not turn optional-check counts into a semantic
score. Worker scheduling, overlap, join policy, and configurable lifecycle
semantics are deferred pending design review.

### Revise, quarantine, rollback

The existing order remains unchanged:

1. revise a live, safely repairable candidate;
2. quarantine the exact candidate when review budget ends without a hard
   provenance failure;
3. rollback only for hard identity, provenance, transaction, destructive, or
   otherwise unsafe-to-repair failure.

Observed value so far is negative-transfer protection and cleaner causal
attribution. It is not yet evidence of an average score gain by itself.

## Verification and backup

- Pre-change backup:
  `.statem/backups/tb3-v2-controls-prechange-20260819/`
- Focused baseline before edits: 48 tests passed.
- Focused result after the three increments: 55 tests passed.
- Full repository result: 665 tests passed, 3 skipped.
- Pre-change snapshot: 11 regular files, 246,951 bytes, deterministic relative
  tree SHA-256
  `da47ee3fa50f38ad35089c043d5687f7b6e43637b3a3585aa301599e0bd2e75a`.
- Post-change snapshot: `.statem/backups/tb3-v2-controls-postchange-20260819/`.
  Its final metrics are recorded in the private branch commit after this file
  is synchronized, avoiding a checksum that describes an earlier document.
- Private GitHub tracking: use a dedicated `codex/` branch in the private
  archive remote. Never push these experimental files to the public `origin`
  until explicitly approved.

## 2026-08-19: v4p17 matched VF2 validation

The first raw validation after the authority and hard-gap changes reuses
`vf2-speedup-networkx` as a matched mechanism test. The prior v4p16 candidate
passed 59 of 60 verifier checks and exact correctness but measured about
888.9x against an explicit 1000x contract. The old protocol nevertheless
handed off after a partial replay.

The v4p17 hypothesis is intentionally narrow: a supported, structured miss of
the explicit quantitative threshold must block promotion and trigger bounded
continued repair or exact-candidate quarantine. It must not be erased by a
passing correctness replay. The stage-portfolio skeleton is not scheduled in
this trial, so any control-flow difference remains attributable to the new
hard-gap path rather than challenger ranking.

Raw reward, protocol validity, and diagnostic evidence remain separate. A
clean zero reward can still validate the control mechanism; a reward of one
does not validate it unless the receipts show independent threshold evidence
and correct promotion behavior.

### v4p17 result and repair

v4p17 was protocol-invalid before falsification, not a task failure. The lead
produced a candidate and immutable snapshot, the preflight worker completed,
and TeamRun reached `decided`, but four solve-to-falsify attempts were blocked.
The worker had returned sensible aliases such as `assertion` and `authority`
inside `contract_ledger`; the lead rewrote them to the gate's required
`claim`, `basis`, and `evidence` schema. The immutable binding correctly
rejected that semantic receipt rewrite, and two bounded session continuations
ended with StateM still in `solve`.

The repair keeps the strict binding. `preflight_task` now carries the exact
item-level ledger schema as structured input, the TeamRun task schema requires
that input, and the reviewer assignment explicitly forbids aliases or lead-side
rewriting. One shared schema constant drives both the task and deterministic
validation. Legal bounded-text normalization uses one canonical projection on
record and replay; a changed claim or incompatible item schema remains a hard
failure.

### v4p18 lifecycle evidence

v4p18 confirmed the schema repair: the completed reviewer result used every
exact ledger item field and reported complete coverage. It could not be
submitted because the local host suspended while the detached reviewer ran.
Worker timeout uses active monotonic time, while the TeamRun lease expires by
wall epoch; after resume, the task had returned to `open` before submission.

The experimental adapter now separates these budgets. Preflight compute remains
480 seconds with a 540-second worker wall budget, while the entry ownership
lease is independently configurable and defaults to 3,600 seconds. The lease
must leave at least 60 seconds beyond the worker wall budget. This tolerates
local suspend/resume and submission cleanup without increasing reviewer compute
or relaxing entry scope, worker count, receipt binding, or final-state checks.
Broader lease renewal and late-result semantics remain deferred lifecycle design
questions rather than core changes.
