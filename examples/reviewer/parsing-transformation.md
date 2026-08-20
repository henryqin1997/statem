# Parsing And Transformation Review

- **`preservation_obligations`**: Define preservation obligations separately from transformed content.
- **`malformed_and_nested_inputs`**: Check malformed, partial, nested, empty, repeated, escaped, encoded, and
  streaming inputs without silently broadening accepted syntax.
- **`encoding_and_offsets`**: Track byte versus character offsets, Unicode normalization, quoting, escaping,
  comments, delimiters, and round-trip stability.
- **`selective_transformation`**: Ensure irrelevant content, ordering, metadata, and formatting survive when
  the task promises a selective transformation.
- **`differential_roundtrip`**: Prefer differential and round-trip checks over examples copied from the
  implementation.
