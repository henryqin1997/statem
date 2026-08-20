# Stateful Systems Review

- **`lifecycle_and_ownership`**: Model lifecycle states, ownership, ordering, and durable versus volatile
  boundaries before reviewing the happy path.
- **`interruption_and_replay`**: Exercise crash/restart, partial write, duplicate delivery, retry, timeout,
  cancellation, concurrent actors, and cleanup.
- **`idempotence_and_visibility`**: Check idempotence and monotonicity of replay, exactly-once claims, stale state,
  resource leaks, lock ownership, and observer-visible intermediate states.
- **`safety_and_liveness`**: Distinguish safety from liveness. A repair that avoids corruption by waiting
  forever is not complete.
- **`external_commit_boundary`**: Verify recovery from the last externally committed point, not from an
  implementation-local flag.
- **`monotone_frontier_reachability`**: When an externally visible progress, commit, or publication frontier
  can advance over state already accepted by a checkpoint or transformation, enumerate every reachable
  intermediate frontier. Exercise multiple pending transitions, partial advancement, interleaving across
  independent owners or objects, and a repeated transformation after partial advancement when task-visible.
  Verify that every future-visible state is preserved while obsolete history is eventually reclaimed.
