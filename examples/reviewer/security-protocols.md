# Security And Protocol Review

- **`trust_and_claim_boundary`**: State the trust boundary and attacker-controlled fields before accepting a
  functional happy path as evidence. Distinguish confidentiality, integrity,
  authenticity, freshness, and availability claims.
- **`framing_and_replay`**: Check framing, canonicalization, length and type validation, partial input,
  truncation, duplicate or reordered messages, replay, downgrade, and failure
  behavior. Reject ambiguous parse-then-verify versus verify-then-parse flows.
- **`secret_and_nonce_ownership`**: Review nonce, IV, salt, sequence, key, and secret ownership. Check reuse,
  uniqueness scope, entropy assumptions, encoding, comparison behavior, and
  whether verification fails closed.
- **`side_channels_and_cleanup`**: Treat error text, timing, logs, temporary files, cleanup, and retries as part
  of the observable security surface. Functional equivalence does not imply
  side-channel or privilege-boundary equivalence.
- **`interoperability_and_known_answers`**: Separate protocol interoperability requirements from implementation-local
  conventions, and use known-answer or metamorphic checks where possible.
