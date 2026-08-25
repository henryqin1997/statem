# TB3 v4p89 prelaunch history gate

## Defect

The existing hyper-level checks validated the requested runtime fields and
practice route, but did not compare a proposed evidence class with preserved
completed results. That allowed KS and Telecom to be preregistered as fresh even
though compatible valid direct observations already existed.

## Gate

`tb3_prelaunch_history_check.py` builds a compact result-only index and emits a
field-validated admission receipt before Harbor, auth, or an environment starts.
It reads result metadata only; it does not index prompts, trajectories, raw
sessions, provider state, or verifier internals.

The evidence classes are:

- `fresh_direct`: reject a compatible prior reward/protocol-valid direct result.
- `infrastructure_replacement`: require no valid prior reward plus a named
  diagnosed boundary change.
- `adapted`: reject an exact adapter-generation duplicate.
- `repeated_calibration` and `sentinel`: admit explicitly as non-score evidence.

Fresh identity is task, model, and agent based across platform and Codex-version
changes. Job-name differences do not create freshness.

## Validation

- Related unit and CLI integration tests: `24` passed.
- Strict hyper-runbook validation: passed.
- Syntax and diff checks: passed.
- Filtered preserved index: `211` TB3 records, SHA256
  `da0ca3b848cd52d8e69c086f078fcc667f7efaad9963ff32231fd38da8e51ce8`.
- KS fresh replay: rejected with two valid compatible observations.
- Telecom fresh replay: rejected with two valid compatible observations.
- Never-observed task replay: admitted and score eligible.

The CLI integration test confirms that a duplicate is rejected and its receipt
is written before Harbor or authentication checks. Future launchers must rebuild
the index from synchronized completed backups, then pin its hash and evidence
class. The gate remains hyper-level and adds no task-agent context.
