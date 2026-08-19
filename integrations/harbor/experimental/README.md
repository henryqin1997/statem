# Parallel Runtime Configuration Experiment

This directory is opt-in and does not change the default `StatemCodex`
submission path or any existing benchmark job.

Use
`integrations.harbor.statem_codex_runtime_config_exp:RuntimeConfigExperimentalStatemCodex`
to start a provenance-constrained control-flow configurator in parallel with
the main agent's `direct_solve`.

Set `STATEM_CONTROL_FLOW_CONFIGURATOR_CMD` to an isolated agent command. The
command receives:

- `STATEM_CONTROL_FLOW_REQUEST`: a compact JSON request containing the visible
  task, general principles, reusable practice catalog, allowed state paths,
  and deadline status.
- `STATEM_CONTROL_FLOW_RESPONSE`: the path where the command should write its
  JSON response.

The command is launched from an empty experiment work directory rather than
the task workspace. A real model command should additionally use its own
read-only sandbox mode.

The experimental Codex adapter defaults to the bundled
`codex_control_flow_agent.py`, which uses `codex exec --sandbox read-only
--ephemeral --ignore-user-config --ignore-rules`. Set
`STATEM_CONTROL_FLOW_CONFIGURATOR_MODE=off` to disable the second model call,
or override `STATEM_CONTROL_FLOW_CONFIGURATOR_CMD` to test a different isolated
agent.

The response cannot contain commands, named gates, unknown paths, task ids,
hidden-verifier references, or acceptance thresholds. Hard task-contract items
must cite exact text from the visible prompt. Agent-inferred risks remain soft
review hypotheses. The runtime always injects the immutable
`task_contract`/`evidence_freshness`/`edge_risk` review lenses; the second agent
only selects optional additions.

`practice_catalog.json` distills reusable engineering review shapes such as
consumer-surface verification, ambiguity preservation, temporal boundary
localization, sequence coordinate/orientation reasoning, state-preserving
recovery, service readiness, dual-contract transformations, numerical sanity,
bounded changes, extraction generalization, deadline-bounded delivery,
fresh-environment replay, representation semantics, held-out evaluation,
performance comparability, structural identification, spatial integrity,
rule-system coverage, and set-valued optimum completeness. It contains no
benchmark task names, known answers, or hidden acceptance values. A practice
reaches the main agent only when the configurator selects it with an exact task
quote; unrelated catalog entries are not copied into the compiled decision.

The configurator also reports materially different task interpretations. Each
ambiguity carries an exact visible quote, candidate interpretations, a
resolution source, and either a justified choice or an explicit request to
preserve alternatives. A `blocking` ambiguity means “resolve before an
irreversible or precision-sensitive choice,” not “apply a hidden pass/fail
gate.”

The delivery plan allocates the visible remaining time among ambiguity
resolution, primary solving, and verification, while preserving the handoff
buffer. Its precision tier and degradation order control work allocation only;
they never change the visible task contract or define correctness. The main
agent may collect this plan once without waiting during `direct_solve`, then
collect again briefly at `task_contract_check`. Invalid, stale, late, or
missing responses fall back to the unchanged thin path.

## Same-model post-verifier proposals

`post_verifier_practice_miner.py` is an optional sidecar for completed trials.
Harbor currently exposes verification-start but not verification-end hooks, and
stops a shared agent environment immediately after verification. The sidecar
therefore invokes the same model family in a fresh read-only ephemeral process
after `result.json` is complete. It receives only the task-visible prompt, the
agent's own StateM review receipt, state names, coarse timing, a pass/zero/error
class, and this reusable catalog. It never receives verifier source, test names,
assertions, expected values, raw sessions, credentials, or environment dumps.

The response is schema-checked and provenance-constrained. It may suggest an
update to an existing practice or a new generic practice, but it cannot emit
commands, answers, named gates, task ids, or numeric acceptance rules. Valid
outputs are marked `validated_proposal_pending_compatibility_review`; they are
not merged automatically. Cross-task compatibility and overhead still require
explicit review before a catalog change.

For hosts that do not install Codex outside Harbor task containers,
`docker_codex_practice_miner.py` provides a clean launcher. It builds a pinned
Codex 0.146.0 image, mounts only the sanitized exchange directory, this
experimental source tree read-only, and an isolated temporary provider-config
home, then deletes the latter with any model session state. It does not mount
the repository root, `.statem`, jobs, backups, or benchmark task containers.
Build and model calls should run only after the measured benchmark job exits so
their CPU and network use cannot perturb task timing.

## Terminal-Bench 3 authority and stage-portfolio controls

`TB3_V2_DESIGN.md` records the incremental repair-aware contract ledger,
mechanical reviewer pre-submit canonicalization, quantitative acceptance-gap
recovery, and the bounded `stage_portfolio_v2.py` protocol. The stage portfolio
is a schema and authorization skeleton, not an enabled default scheduler. It
keeps semantic ranking with an independent reviewer, integration with the lead,
and final promotion behind untouched replay.

`candidate_acceptance_replay.py` adds a separate execution-provenance layer for
the evidence-develop v4 runbook. The lead declares one to four bounded public
checks as argv arrays. The adapter validates exact proposal, solver evidence,
and immutable snapshot bindings, then executes each check in a fresh disposable
snapshot copy with a minimal environment, wall/output/process-group budgets,
and digest-only output capture. Failed checks are semantic evidence rather than
protocol exceptions; stale bindings, sensitive values, or mutation of the live
candidate or immutable snapshot are protocol failures. The resulting receipt
proves independent execution of a solver-selected plan, not independent test
selection or automatic promotion authority.
