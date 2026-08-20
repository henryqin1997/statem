# Numerical And Statistical Review

- **`variant_definition`**: Identify the exact estimator, statistic, discretization, or optimization
  variant. Distinguish plausible variants with a small analytic or executable
  case; do not infer the definition from the implementation's own docstring.
- **`finite_sample_terms`**: Check finite-sample denominators, diagonal/self terms, replacement versus
  no-replacement sampling, bias correction, degrees of freedom, and whether an
  estimate is mathematically allowed to be negative.
- **`range_transforms`**: Challenge clipping, clamping, normalization, epsilon insertion, rounding, and
  range assumptions against the actual definition.
- **`tensor_numeric_semantics`**: Check shape semantics, axis reductions, coordinate identity, broadcasting,
  dtype promotion, mutation, NaN/Inf handling, overflow, underflow, and
  cancellation.
- **`calibration_resampling`**: For randomized calibration or resampling, check seed ownership, reproducible
  replay, sample-size boundaries, and whether the null/reference population is
  contaminated by current observations.
- **`invariant_checks`**: Prefer invariants and metamorphic checks in addition to fixed examples.
