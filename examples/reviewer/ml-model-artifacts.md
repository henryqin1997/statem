# ML Model And Artifact Review

- **`execution_and_artifact_contract`**: Identify whether the contract concerns training, evaluation, inference,
  serialization, consolidation, or migration. Bind model mode, device, dtype,
  shape, layout, and framework-version assumptions explicitly.
- **`state_identity_and_shards`**: Check parameter versus buffer identity, tied weights and aliases, optimizer
  and scheduler state, shard coverage, missing or duplicate keys, metadata, and
  deterministic ordering. A numerically equal copy may still violate alias or
  storage semantics.
- **`metric_and_population_semantics`**: For metrics and monitoring, check sample population, label and mask
  alignment, train/eval leakage, calibration, aggregation weights, reduction
  axes, class imbalance, threshold ownership, and the exact statistical
  definition.
- **`boundary_shapes_and_replay`**: Exercise empty, singleton, uneven-shard, mixed-precision, non-contiguous,
  missing-field, and resume/replay cases. Check random seed ownership without
  mistaking one deterministic seed for distributional validation.
- **`public_consumer_load_path`**: Compare the public consumer's load or evaluation path on baseline and
  candidate; file existence and successful deserialization alone are not
  sufficient evidence.
