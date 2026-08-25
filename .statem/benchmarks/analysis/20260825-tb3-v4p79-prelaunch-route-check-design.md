# TB3 v4p79 prelaunch route check

## Scope

- Keep StateM core and the task runbook unchanged.
- Add a host-side hyper-agent admission check before Harbor, authentication, or
  environment setup.
- Use the same visible-instruction selector and exact catalog as the thin-family
  adapter. Do not force an adapted practice when visible routing disagrees.

## Public core audit

The public strict-field and bounded-attempt implementation from commit
`a321fc0` is already an ancestor of this experiment branch. Focused tests for
`max_attempts`, strict unknown-field rejection, and misplaced-field rejection
pass. No duplicate core merge was made.

## Admission contract

An adapted launch must bind one task, one visible `instruction.md`, one catalog,
`activation_mode=active`, and an exact `development_practice_id`. The receipt
uses a closed field set, SHA256-binds the instruction, catalog, and receipt, and
is written atomically. Only an exact visible selector match is admitted.

`--prelaunch-only` exits before Harbor executable, auth, and environment checks.
This supports cheap route debugging without consuming a benchmark lane.

## Validation

- 16 focused prelaunch and thin-family tests pass.
- Three focused public strict-validation tests pass.
- Both hyper and task runbooks pass `statem validate --strict`.
- Real visible-input dry runs: SATB/audio is admitted; KS/numerical is rejected
  before Harbor. Both receipts pass strict field and hash validation.
- A broad legacy CLI run has six source-closure failures because this frozen
  experiment branch lacks historical `teamrun-video-search` and `progress.md`
  example files. None execute the changed prelaunch path.

## Remote rollout rule

Run prelaunch-only admission against the frozen remote manifest before occupying
an AWS lane. Launch only an admitted route with the identical catalog path and
adapter kwargs; archive the receipt with the job evidence.
