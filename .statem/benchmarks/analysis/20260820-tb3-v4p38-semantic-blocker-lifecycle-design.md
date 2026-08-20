# TB3 v4p38 semantic blocker lifecycle repair

## Failure owner

The v4p37 risk sentinel made substantive task progress: it built and replayed
multiple candidates, ran independent falsifiers, quarantined a candidate, and
opened one deadline-feasible repair cycle. It then repeated the same
solve-to-falsify validation-delta blocker ten times. Draft and artifact hashes
changed on each host resume, so the previous progress identity reset its
no-progress counter and exhausted the hard resume cap in `solve`.

This is a host lifecycle accounting defect. It is not task-agent capability,
reviewer counterevidence, verifier feedback, or hardware insufficiency.

## Minimal repair

- Within one StateM entry, fingerprint the latest blocking transition failure.
- When a blocker exists, let that semantic fingerprint dominate draft and
  artifact churn for no-progress accounting.
- Preserve ordinary artifact and receipt progress semantics when no transition
  blocker exists.
- Delete an earlier validation-delta success receipt before validating a newer
  attempt, so failed validation cannot leave stale success evidence.
- Keep the v4p35 runbook, family router, task contract, reviewer verdict,
  promotion gate, revise/quarantine/rollback order, and deadline policy
  unchanged.

## Validation

- Focused failure-closure and recovery suites: 62 tests passed.
- Strict inherited v4p35 runbook validation: passed.
- Full suite: 725 tests run, 11 skipped, one known unrelated failure in the
  isolated git-webserver-family subprocess because it cannot import the local
  `statem` package.
- Source commit: `c9f5f61`.
- Canonical source manifest: 35 files,
  `105d1db1dc405b2643d989407a72777d82ce11fc869290f0a5b96689784bf46e`.

## Promotion rule

v4p38 is unpromoted. Run exactly one repeated standard-timeout k1 risk sentinel
against the preserved protocol-valid raw-one direct baseline. It must reach a
protocol-valid handoff and preserve raw reward 1.0 before the unsigned fresh
`data-anonymization` half can launch. If the same lifecycle hypothesis produces
no new reproducible discriminator or replayable milestone, park it and advance
the 0/5 queue.
