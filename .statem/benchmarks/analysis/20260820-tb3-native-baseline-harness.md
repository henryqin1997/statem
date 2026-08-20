# TB3 native matched-baseline harness

## Purpose

Fresh score claims require an unadapted direct Codex cell matched to each
StateM cell by model, Codex version, task sample, platform, timeout, and retry
policy. The baseline must also satisfy the experiment's ChatGPT-auth and
no-raw-session publication constraints.

## Minimal wrapper

`AuthNoSessionCodex` delegates the benchmark instruction and execution directly
to Harbor's installed `Codex` agent. It does not prepend a prompt, install a
runbook, select a route, add a reviewer, resume a session, or change the task
budget.

The wrapper has two operational responsibilities only:

1. request file-backed credential storage when `CODEX_AUTH_JSON_PATH` is
   configured; and
2. convert the copied Codex session to Harbor ATIF, then remove the raw session
   directory from both the task artifact volume and local logs.

Raw-session cleanup is mandatory rather than best effort. A cleanup failure is
a protocol failure, not a valid direct result.

## Comparability

The direct wrapper has a distinct identity,
`codex-auth-no-session-baseline-v1`, so its evidence cannot be confused with a
StateM adapter. Matched reports must retain both agent identities and must not
call this wrapper a StateM route.
