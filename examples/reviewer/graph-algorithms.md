# Graph Algorithm Review

- **`graph_model_semantics`**: Resolve directed versus undirected, simple versus multi-graph, induced versus
  non-induced, and node-induced versus edge-induced semantics.
- **`structural_edge_cases`**: Check self-loops, parallel edges, disconnected components, empty/singleton
  graphs, attribute and label matching, node ordering, and input mutation.
- **`pruning_soundness`**: Treat pruning as a proof obligation: every pruning rule must be necessary for
  a valid match, not merely correlated with common cases.
- **`bounded_oracle`**: Compare optimized behavior to a bounded trusted oracle or exhaustive search
  on small adversarial graphs. Include cases that defeat degree-only, neighbor
  count, color, and ordering heuristics.
- **`enumeration_semantics`**: Check completeness, duplicate suppression, mapping orientation, deterministic
  output conventions, and early termination.
- **`scaling_behavior`**: Measure complexity on a small scaling ladder and separate algorithmic speedup
  from cache artifacts or changed semantics.
