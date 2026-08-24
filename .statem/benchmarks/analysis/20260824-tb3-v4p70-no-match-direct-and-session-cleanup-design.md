# TB3 v4p70 no-match direct routing and session cleanup

## Evidence owner

The v4p69 HOF Daytona StateM arm selected and activated no family practice but
still ran two solve/verify cycles plus self-review. It took 1791 seconds versus
1340 for direct and left one locally downloaded raw Codex session after ATIF
conversion. Both arms scored raw zero; the controller defects are independent
of task reward and can be repaired offline.

## Minimal repair

1. `StatemCodex._remove_codex_session_logs` now removes both the remote session
   copy and the local cloud-download directory after ATIF conversion.
2. v4p70 computes the visible-instruction family selection before starting a
   StateM run. If no admitted practice is activated, it invokes native Codex
   with the original task instruction and baseline CLI flags. It records a
   compact `native_direct_bypass` route receipt but creates no StateM graph.
3. Only an admitted active family practice enters the unchanged 86-line thin
   runbook. Unadmitted matches remain visible in metadata but cannot add solver
   context or reviewer work.

This is adapter routing, not a new global state or a heavier runbook.

## Validation

- 22 focused tests pass.
- Strict validation of the unchanged thin runbook passes.
- The sparse worktree full suite reports 298 pass, 1 skip, and 7 failures; all
  seven reference historical ignored fixtures/examples absent from this sparse
  experiment tree and are unrelated to the modified files.
- Live admission sentinel: adapted `react-lead-form`, whose preserved v4p66
  direct arm scored raw one. v4p70 must select the existing unadmitted
  stateful-lifecycle match, keep it inactive, execute `native_direct_bypass`,
  retain no StateM graph or raw session, and reach a verifier result. The raw
  reward is a negative-transfer observation, not fresh score evidence.

## Live validation outcome

The React sentinel passed raw `1.0` with valid protocol. Its route receipt was
`stateful_lifecycle_compact`, `admitted=false`, `activated=false`, and
`execution_mode=native_direct_bypass`. It produced ATIF-v1.5 with complete
usage, no StateM state directory, no reviewer or resume, and no raw session.
This admits the direct-bypass routing and cloud cleanup repair. It does not
admit the lifecycle practice itself.
