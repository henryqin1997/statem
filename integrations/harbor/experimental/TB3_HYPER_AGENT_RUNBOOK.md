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
counterfactual. A useful practice contains only:

1. an observable task-contract trigger;
2. the earliest wrong choice;
3. one bounded intervention and public discriminator;
4. protected behavior and a stop rule;
5. a compact solver projection and separate detailed reviewer projection.

When several controls changed together, retain a composite hypothesis rather
than claiming a component effect. Isolate it through the cheapest validation
that can decide the question.

## Cheap preflight

The hyper orchestrator first uses a candidate-blind task card plus existing raw
evidence. Deterministic checks reject configuration, platform, route, deadline,
and missing-public-discriminator mismatches. A bounded subagent is used only to
execute a public smoke test or distinguish solver-direction from validation
ownership. Full task rollouts are not controller debugging tools.

## Information-gain budget

Every continuation declares the hypotheses separated, predicted observation,
validation delta, expected cost, deadline feasibility, and the decision that
would change. Prefer the experiment with the largest expected change in
admission, rebranch, transfer, or parking per unit cost. A `0 -> 0` closes one
comparison, not the task; park only after proposal exhaustion, absent public
discriminators, a capability or hardware boundary, or lower value than the
next eligible task.

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
