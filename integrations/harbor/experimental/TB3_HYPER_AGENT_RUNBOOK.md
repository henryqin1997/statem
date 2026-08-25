# TB3 hyper-agent development runbook

This runbook controls experiments, not benchmark-task execution. Its StateM
graph is `examples/tb3-hyper-agent-development-v1.yaml`. No state prompt from
this graph may be projected into a task solver or task reviewer.

## Evidence lanes

| Lane | Purpose | Admission |
| --- | --- | --- |
| Scoring | Unbiased frozen comparison | Untouched sample and no between-arm tuning |
| Develop | Causal attribution and practice extraction | New public discriminator or measurable validation delta |
| Safety | Detect scoped negative transfer | Route, context, gate, or artifact authority changed |

Safety is intentionally low frequency. Terminal-Bench 2.1 already establishes
that precise routing protects ordinary tasks; TB3 repeats a sentinel only when
the changed control creates a new plausible exposure.

## Adapted extraction loop

An adapted result cannot estimate an unbiased score, but it may be the strongest
evidence for a control. Compare positive and negative behavior, locate the first
decision that predicts the outcome, classify its owner, and test one bounded
counterfactual. Start at the narrowest scope supported by that contrast. Do not
guess one general control and repeatedly deploy it across tasks. Develop local
controls independently, then synthesize only the mechanism shared by convergent
positive and negative observations. A useful practice contains only:

1. an observable task-contract trigger;
2. the earliest wrong choice;
3. one bounded intervention and public discriminator;
4. protected behavior and a stop rule;
5. a compact solver projection and separate detailed reviewer projection.

When several controls changed together, retain a composite hypothesis rather
than claiming a component effect. Isolate it through the cheapest validation
that can decide the question.

## Scope ladder

Every extracted control records one scope and one promotion status:

| Scope | Meaning | Expansion evidence |
| --- | --- | --- |
| Task | One implementation or contract surface | Same-task causal delta |
| Subfamily | A precise repeated shape inside a family | Convergent local mechanisms |
| Family | Shared mechanism under a visible family route | Frozen family-level discriminator |
| Global | Cross-family controller or lifecycle invariant | Cross-family convergence and scoped safety evidence |

Keep non-common details in task or subfamily practices with precise routing.
Expand scope only when the broader control produces positive transfer. A merely
non-regressing result does not justify expansion. Mark answer-shaped triggers,
sample-specific thresholds, post-hoc checks, and non-discriminating evidence as
`hack_risk: review_required`; do not promote them before human review.

## Three-stage pipeline

1. **Local development:** obtain or reuse raw evidence, diagnose the owner, and
   validate the smallest task or subfamily control.
2. **Convergence synthesis:** compare independently developed controls and
   extract only their common mechanism. Family synthesis requires at least two
   independent local analyses with the same earliest consequential mechanism;
   similar wording or desired outcomes are insufficient. No rollout is
   required when no common mechanism is observed.
3. **Scope validation:** freeze the synthesized family or global control and run
   the cheapest discriminator of the scope expansion, including its precise
   selector. This validates the shared abstraction, not a transfer of the first
   task's practice, and is not a requirement to promote every local practice
   one by one.

## Cheap preflight

The hyper orchestrator first uses a candidate-blind task card plus existing raw
evidence. Deterministic checks reject configuration, platform, route, deadline,
runtime-field, and missing-public-discriminator mismatches. Unknown task fields
fail before auth or environment startup instead of being silently discarded and
misclassified as solver failures. A bounded subagent is used only to execute a
public smoke test or distinguish solver-direction from validation ownership.
Full task rollouts are not controller debugging tools.

## Information-gain budget

Every continuation declares the hypotheses separated, predicted observation,
validation delta, expected cost, deadline feasibility, and the decision that
would change. Prefer the experiment with the largest expected change in
admission, rebranch, scope, or parking per unit wall time. API cost is a
constraint, not the primary search objective. A `0 -> 0` closes one comparison,
not the task; park only after proposal exhaustion, absent public discriminators,
a capability or hardware boundary, or lower value than the next eligible task.

## Layer boundary

- Hyper runbook: portfolio, lanes, evidence role, information gain, transfer,
  score accounting, and stopping.
- TB3 task runbook: one thin solve/verify/review/handoff execution and its
  controller-owned gates.
- Practice catalog: compact solver obligations plus reviewer-only detailed
  checks.
- Audit ledger: full receipts, history, costs, and eligibility.

Historical results, task rankings, score targets, and adapted findings never
enter task-agent context. Task-level routing never decides experiment priority.
