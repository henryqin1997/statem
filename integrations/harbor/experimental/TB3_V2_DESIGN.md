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
