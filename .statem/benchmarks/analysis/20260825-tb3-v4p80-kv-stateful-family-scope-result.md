# TB3 v4p80 KV stateful scope result

## Verdict

The replacement matched pair completed as direct `0.0` and StateM `0.0` with
no runner errors or retries. Both raw rewards are reward-valid, but the frozen
family-scope experiment is protocol-invalid: all preregistered public loadgen
artifacts failed collection in both arms. Exclude this pair from fresh score
and control-scope evidence.

This is not evidence for stateful family promotion. It also does not isolate a
KV implementation failure. The diagnosed owner is the harness boundary that
collects public artifacts across services. The same boundary failed on Daytona
and AWS Docker, so do not run another KV replacement until that collector is
repaired and cheaply dry-run against the public producer path.

## Matched result

| Arm | Raw | Reward-valid | Scope protocol | Cost | Wall | Tokens (input/cache/output) |
| --- | ---: | --- | --- | ---: | ---: | --- |
| Direct | 0.0 | yes | invalid | $6.079963 | 2135.470 s | 9,774,076 / 9,558,528 / 69,718 |
| StateM | 0.0 | yes | invalid | $3.517668 | 1539.065 s | 4,754,838 / 4,579,840 / 49,287 |

Both arms used GPT-5.6 Sol max, Codex 0.149.1, standard timeout, no retry,
AWS x86_64 Docker, ATIF-v1.5, and no raw session paths. The first launch was
auth-invalid before task execution and is reported separately; refreshed-auth
replacement jobs are the rows above.

StateM selected `stateful_lifecycle_compact` by an exact host prelaunch route
receipt, activated it only through the explicit development override, and
finished at `handoff`. The practice remained unadmitted. The broad selector is
also false-heavy for known-direct tasks, as recorded in the pre-result route
audit addendum; production activation stays blocked independently of reward.

## Public evidence gap

The artifact manifests in both arms report the public artifact directory as
empty and the expected results, measurement, and loadgen files as failed. No
hidden-verifier evidence was inspected. Therefore the raw zeros cannot support
a development-versus-validation diagnosis or a new task practice.

## Scope decision

- Do not expand `stateful_lifecycle_compact` from its current candidate scope.
- Do not author a KV-specific practice from this pair.
- Keep MVCC and WAL evidence at their previously supported scopes.
- Repair and preflight public cross-service artifact collection before another
  KV causal cell.
- Continue local-first development elsewhere; synthesize a broader stateful
  control only after independently developed mechanisms actually converge.

## Preservation

| Arm | Files | Bytes | Relative-path tree SHA256 |
| --- | ---: | ---: | --- |
| Direct | 13 | 863,553 | `1350e613d61f27df7cdcb692055582b17fac27a9488d8fa8c430a3700f7ed45f` |
| StateM | 27 | 793,457 | `91fb988cb7c7d142fb6bef76575646b8327ff99c99e13ead2eeec763ba176e9d` |

Remote and local values match; both checksum dry-runs were empty. Complete jobs
are preserved under `.statem/benchmarks/backups` in the primary workspace.
