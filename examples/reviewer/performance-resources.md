# Performance And Resource Review

- **`semantic_equivalence`**: Establish semantic equivalence before measuring speed. Check that pruning,
  caching, batching, approximation, vectorization, and parallelism preserve the
  required output set, ordering, precision, mutation, and failure behavior.
- **`scaling_and_adversarial_paths`**: Separate asymptotic improvement from constant-factor improvement. Exercise
  adversarial structure, skew, sparsity or density, cache misses, fallback
  paths, and the size at which the proposed strategy changes behavior.
- **`complete_resource_accounting`**: Account for wall time, CPU, accelerator, memory peak, allocations, I/O,
  process startup, synchronization, and cleanup. Moving work outside the timed
  region or leaking resources is not an improvement.
- **`paired_measurement_validity`**: Use paired baseline/candidate measurements with the same fixture, warmup,
  environment, and correctness oracle. Report variance and avoid treating one
  noisy sample as a blocking regression.
- **`acceptance_population_and_margin`**: Separate exploratory examples from the acceptance population. Predeclare
  or deterministically generate a broad, non-cherry-picked population before
  reading comparative timings; assign stable population ids and evidence roles.
  Declare the population's algorithmically decisive support dimensions,
  selection basis, eligible ranges or categories, boundary/interior strata, and
  uncovered regions. Fresh nuisance variables such as seeds, payloads, labels,
  keys, or prose do not create a fresh acceptance population when structural
  parameters copy the exploration set or the candidate's favored schedule. A
  fixed-before-execution population can still be structurally cherry-picked.
  Once a sample or population has influenced diagnosis, implementation, or
  challenger selection, it is exploration evidence and cannot be relabeled as
  final acceptance evidence. Keep a separately generated acceptance population
  untouched until the candidate is bound; a failed acceptance population may
  become exploration input for the next cycle only after that cycle receives a
  fresh untouched acceptance population. Prefer a contiguous or independently seeded
  schedule whose membership cannot depend on observed speed, and retain
  unusually fast baseline cases and other unfavorable cases. For a hard ratio
  threshold, use at least ten acceptance fixtures when individual fixtures are
  inexpensive enough; otherwise record the cost-based sample-size rationale
  and require stronger held-out and variance evidence. Use independent replays
  or a held-out population, report the aggregate used by the contract together
  with its distribution and worst relevant tail, and require a noise margin
  justified by observed run-to-run variance. Treat a hard numerical gate as
  unresolved until an independent acceptance aggregate and its conservative
  lower confidence or repeatability bound clear the threshold with that margin.
  Continue bounded bottleneck optimization while time and handoff reserve remain;
  stop after the margin is met, after the declared non-improving challenger
  budget, or when correctness regresses. A threshold result that
  changes verdict across consumer-equivalent replays is `revise`, not
  promotion evidence. A sealed benchmark population that no authorized role can
  execute is residual acceptance uncertainty, not an observed threshold miss.
  Do not spend recovery cycles trying to obtain unavailable labels or invent a
  provider allocation; continue only when a bounded public experiment can
  discriminate between candidates.
  Treat an enumerable but untested public fallback region as an actionable
  coverage gap rather than sealed uncertainty. A post-adaptation population
  must not merely reproduce the prior structural multiset with new nuisance
  values.
- **`consumer_execution_model`**: Replay the complete measured path under the consumer's CPU, memory, process,
  privilege, filesystem, import/startup, and concurrency model. Include
  wrappers, conversions, cache state, process boundaries, and the full
  acceptance population. Enumerate every public construction and mutation
  surface that can change cache readiness; when both incremental and bulk
  builders exist, replay both rather than assuming one represents the
  consumer. A faster inner kernel is insufficient when the consumer times a
  larger end-to-end operation.
- **`cache_readiness_and_first_call`**: If performance depends on preprocessing, memoization, compilation, or a
  construction-time certificate, measure the first consumer call after each
  supported construction path as well as warm repeated calls. Attribute all
  work that makes the cache ready, and reject evidence that moves untimed work
  into a favored builder hook without proving the consumer uses that hook.
- **`bounded_resource_behavior`**: Check bounded-resource and cancellation behavior. A faster happy path that
  loses progress, starves peers, or becomes unresponsive under limits is a
  semantic regression. Give every exploratory benchmark, adversarial case, and
  fallback probe an explicit wall timeout and process-group cleanup path;
  preserve a timeout as negative evidence instead of waiting indefinitely or
  silently discarding the case.
