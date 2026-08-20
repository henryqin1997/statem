from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

from integrations.harbor.statem_codex import TeamRunStatemCodex


class MultiRoleDevelopExperimentalStatemCodex(TeamRunStatemCodex):
    """Minimal solver/falsifier StateM experiment with deterministic promotion."""

    _LOCAL_ARTIFACT_IDENTITY = (
        Path(__file__).resolve().parent / "experimental" / "artifact_identity.py"
    )
    _LOCAL_PROMOTION_GATE = (
        Path(__file__).resolve().parent
        / "experimental"
        / "multirole_promotion_gate.py"
    )
    _REMOTE_PROMOTION_GATE = PurePosixPath(
        "/tmp/statem-verification-checks/multirole_promotion_gate.py"
    )
    _REMOTE_RECEIPTS = PurePosixPath(
        "/tmp/statem-verification-checks/multirole"
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        reviewer_model: str = "gpt-5.6-sol",
        reviewer_reasoning_effort: str = "max",
        reviewer_timeout_seconds: int = 240,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-multirole-develop-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            run_id_prefix="tb3-multirole-develop",
            **kwargs,
        )
        if reviewer_timeout_seconds < 30:
            raise ValueError("reviewer_timeout_seconds must be at least 30")
        self._reviewer_model = reviewer_model
        self._reviewer_reasoning_effort = reviewer_reasoning_effort
        self._reviewer_timeout_seconds = int(reviewer_timeout_seconds)

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-multirole-develop-exp"

    def _verification_check_paths(self) -> list[Path]:
        deadline = (
            self._statem_source_dir
            / "integrations"
            / "harbor"
            / "verification_checks"
            / "deadline_status.py"
        )
        paths = [self._LOCAL_ARTIFACT_IDENTITY, self._LOCAL_PROMOTION_GATE]
        if deadline.is_file():
            paths.append(deadline)
        stop_hook = (
            self._statem_source_dir
            / "integrations"
            / "hooks"
            / "statem_stop_hook.py"
        )
        if stop_hook.is_file():
            paths.append(stop_hook)
        return paths

    def _statem_env(self, run_id: str) -> dict[str, str]:
        env = super()._statem_env(run_id)
        env["STATEM_AGENT_ROLE"] = "solver"
        return env

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        timeout = self._reviewer_timeout_seconds
        return_slack = min(90, max(30, timeout // 6))
        wall_timeout = timeout + return_slack
        lease_seconds = wall_timeout
        return f"""You are {self.name()}, the solver in a minimal role-separated StateM experiment.

StateM owns lifecycle, identity, scoped receipts, and deterministic promotion
authorization. Artifact storage and rollback remain task-native external
operations. Never edit the runbook, gate, source manifest, task prompt, TeamRun
state, or another agent's receipt.

Required protocol:
- Inspect the current state before substantive work with `statem cur` using run
  id {run_id} and state dir {state_dir}.
- Move only through explicit StateM transitions.
- In solve, preserve a real rollback locator before mutation and record exactly
  one candidate proposal through {self._REMOTE_PROMOTION_GATE.as_posix()}.
- In falsify, use the already initialized one-task TeamRun. Launch exactly one
  fresh falsifier with:
  `statem-teamrun-codex-workers --run-id {run_id} --state-dir {state_dir}
  --entry-id <current-entry-id> --cwd /app --max-workers 1 --max-rounds 1
  --timeout {timeout} --wall-timeout {wall_timeout} --return-slack {return_slack}
  --lease-seconds {lease_seconds} --agent-prefix falsifier --agent-role
  falsifier --execution-profile read-only-review --model
  {shlex.quote(self._reviewer_model)} --reasoning-effort
  {shlex.quote(self._reviewer_reasoning_effort)} --no-unified-exec --json`.
- The falsifier is read-only and receives a trusted bounded context projection
  embedded in its assignment. It must not call tools, repair the candidate, or
  inspect excluded information classes listed in the context-view receipt.
- After the worker submits, advance TeamRun to reducing and run the built-in
  all-claims-table reducer. Follow only the deterministic gate and review
  guard's promote, revise, quarantine, or rollback edge.
- A promote authorization is not an artifact transaction. Activate or restore
  with the task-native provider, then let the next StateM hook verify the live
  identity. Do not treat an unverified operation as committed.
- Review-budget exhaustion stops more review; it does not prove the candidate
  wrong. Quarantine the exact reviewed snapshot for candidate-bound replay when
  no hard provenance or transaction failure requires rollback.
- Use only task-visible files and public consumer behavior. Never inspect hidden
  benchmark artifacts, verifier internals, credentials, provider config, raw
  model sessions, or public benchmark solutions.

Current StateM state summary:
{current_context.strip()}

Benchmark task:
{instruction}
"""

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        await super()._collect_statem_artifacts(environment, context, run_id)
        agent_statem_dir = (
            PurePosixPath(EnvironmentPaths.agent_dir.as_posix()) / "statem"
        )
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"cp -R {shlex.quote(self._REMOTE_RECEIPTS.as_posix())} "
                    f"{shlex.quote((agent_statem_dir / 'multirole').as_posix())} || true"
                ),
                env=self._statem_env(run_id),
            )
        except Exception:
            pass


class RecoveringMultiRoleDevelopExperimentalStatemCodex(
    MultiRoleDevelopExperimentalStatemCodex
):
    """Bounded recovery loop with an independent per-cycle falsifier."""

    _LOCAL_RECOVERY_GUARD = (
        Path(__file__).resolve().parent
        / "experimental"
        / "recovering_develop_guard.py"
    )
    _REMOTE_RECOVERY_RECEIPTS = PurePosixPath(
        "/tmp/statem-verification-checks/recovering-develop"
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-recovering-multirole-develop-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-recovering-multirole-develop-exp"

    def _verification_check_paths(self) -> list[Path]:
        return [*super()._verification_check_paths(), self._LOCAL_RECOVERY_GUARD]

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        base = super()._augment_instruction(instruction, run_id, current_context)
        return base + """

Recovery-cycle controls:
- Keep ordinary recoverable debugging in the lead solver context. Use the
  read-only child only after a complete candidate exists and only for
  falsification, semantic anchoring, and regression evidence.
- The recovery guard allows at most two candidate cycles. A second cycle must
  be justified by one concrete failure from final public replay or by a
  structured hard quantitative contract gap that final replay did not resolve
  with fresh independent acceptance evidence. Novelty or generic reviewer
  uncertainty alone is not a retry reason.
- In repair tasks, task wording and public signatures are hard constraints;
  behavioral docstrings in explicitly broken target modules are defeasible
  hypotheses that require independent semantic or domain corroboration.
- Promotion is monotonic across cycles because each new cycle seals the
  previously verified selected artifact, while public contract preservation is
  checked on every promotion.
"""

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        await super()._collect_statem_artifacts(environment, context, run_id)
        agent_statem_dir = (
            PurePosixPath(EnvironmentPaths.agent_dir.as_posix()) / "statem"
        )
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"cp -R {shlex.quote(self._REMOTE_RECOVERY_RECEIPTS.as_posix())} "
                    f"{shlex.quote((agent_statem_dir / 'recovering-develop').as_posix())} || true"
                ),
                env=self._statem_env(run_id),
            )
        except Exception:
            pass


class EvidenceDevelopV4ExperimentalStatemCodex(
    RecoveringMultiRoleDevelopExperimentalStatemCodex
):
    """Evidence-gated recovery with provider-owned filesystem transactions."""

    _LOCAL_ARTIFACT_PROVIDER = (
        Path(__file__).resolve().parent
        / "experimental"
        / "filesystem_artifact_provider.py"
    )
    _REMOTE_ARTIFACT_PROVIDER = PurePosixPath(
        "/tmp/statem-verification-checks/filesystem_artifact_provider.py"
    )
    _REMOTE_PROVIDER_RECEIPTS = PurePosixPath(
        "/tmp/statem-verification-checks/artifact-provider"
    )
    _LOCAL_ACCEPTANCE_REPLAY = (
        Path(__file__).resolve().parent
        / "experimental"
        / "candidate_acceptance_replay.py"
    )
    _REMOTE_ACCEPTANCE_REPLAY = PurePosixPath(
        "/tmp/statem-verification-checks/candidate_acceptance_replay.py"
    )
    _LOCAL_ACTIVATION_GATE = (
        Path(__file__).resolve().parent
        / "experimental"
        / "develop_activation_gate.py"
    )
    _LOCAL_REVIEWER_PRACTICES = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "reviewer-practices-v1.yaml"
    )
    _LOCAL_REVIEWER_PROFILE_CATALOG = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "reviewer-practice-router-v1.yaml"
    )
    _LOCAL_REVIEWER_PROFILES = tuple(
        sorted(
            (Path(__file__).resolve().parents[2] / "examples" / "reviewer").glob(
                "*.md"
            )
        )
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        reviewer_reasoning_effort: str = "high",
        reviewer_timeout_seconds: int = 900,
        preflight_reviewer_reasoning_effort: str = "medium",
        preflight_reviewer_timeout_seconds: int = 480,
        preflight_reviewer_lease_seconds: int = 3600,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            reviewer_reasoning_effort=reviewer_reasoning_effort,
            reviewer_timeout_seconds=reviewer_timeout_seconds,
            enforce_final_state=True,
            max_session_resumes=8,
            **kwargs,
        )
        if preflight_reviewer_timeout_seconds < 30:
            raise ValueError("preflight_reviewer_timeout_seconds must be at least 30")
        self._preflight_reviewer_reasoning_effort = (
            preflight_reviewer_reasoning_effort
        )
        self._preflight_reviewer_timeout_seconds = int(
            preflight_reviewer_timeout_seconds
        )
        preflight_slack = min(
            60, max(30, self._preflight_reviewer_timeout_seconds // 8)
        )
        minimum_lease = (
            self._preflight_reviewer_timeout_seconds + preflight_slack + 60
        )
        if preflight_reviewer_lease_seconds < minimum_lease:
            raise ValueError(
                "preflight_reviewer_lease_seconds must leave at least 60 seconds "
                "after the worker wall budget"
            )
        self._preflight_reviewer_lease_seconds = int(
            preflight_reviewer_lease_seconds
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4-exp"

    def _verification_check_paths(self) -> list[Path]:
        return [
            *super()._verification_check_paths(),
            self._LOCAL_ARTIFACT_PROVIDER,
            self._LOCAL_ACCEPTANCE_REPLAY,
            self._LOCAL_ACTIVATION_GATE,
            self._LOCAL_REVIEWER_PRACTICES,
            self._LOCAL_REVIEWER_PROFILE_CATALOG,
            *self._LOCAL_REVIEWER_PROFILES,
        ]

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        base = super()._augment_instruction(instruction, run_id, current_context)
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        preflight_timeout = self._preflight_reviewer_timeout_seconds
        preflight_slack = min(60, max(30, preflight_timeout // 8))
        preflight_wall = preflight_timeout + preflight_slack
        preflight_lease = self._preflight_reviewer_lease_seconds
        preflight_handle = (
            "/tmp/statem-verification-checks/multirole/preflight-worker.json"
        )
        return base + f"""

Evidence-develop v4 controls:
- The filesystem artifact provider, not StateM core, owns immutable baseline and
  candidate snapshots. Never modify anything under
  {self._REMOTE_PROVIDER_RECEIPTS.as_posix()}/snapshots.
- In solve and revise, after writing proposal-draft.json, run the proposal gate,
  then snapshot the candidate with:
  `python3 {self._REMOTE_ARTIFACT_PROVIDER.as_posix()} snapshot --kind candidate
  --artifact-root /app --expected-receipt
  /tmp/statem-verification-checks/multirole/candidate-proposal.json --output
  /tmp/statem-verification-checks/artifact-provider/candidate-snapshot.json`.
- Before leaving solve or revise, record bounded public self-verification in
  acceptance-evidence-draft.json using the exact schema in the current StateM
  prompt. Copy the current candidate artifact identity exactly. The state hook
  binds this solver attestation to the proposal and immutable snapshot; it is
  evidence for independent review, never promotion authority by itself.
- Also write acceptance-replay-plan-draft.json using the exact bounded schema
  in the current StateM prompt. Bind it to the preflight reviewer's
  candidate-blind acceptance plan and map each executable requirement to at
  least one public check; do not turn analytic or paired-review obligations into
  command-shaped proxies merely to satisfy the schema. Declare only public,
  non-interactive checks with argv arrays, relative working directories,
  explicit expected exit codes, and short timeouts. The adapter replays each
  check on a fresh disposable copy of
  the immutable candidate snapshot with a minimal credential-free environment,
  process-group limits, and digest-only output. A replay receipt proves what
  executed on which candidate; it does not prove that the selected checks cover
  the task contract.
- protected_behavior_basis is machine validated. A broken target docstring is
  never a sufficient basis by itself.
- In contract_audit, select one primary and at most two secondary reviewer
  profiles before candidate work. The bound reviewer profile is procedural
  memory for the task category, not task-specific solution memory.
- In solve, use two channels only. Before the first mutation, write the exact
  solver-plan draft required by the runbook, then run:
  `python3 {self._REMOTE_PROMOTION_GATE.as_posix()} plan --draft
  /tmp/statem-verification-checks/multirole/solver-plan-draft.json --seal
  /tmp/statem-verification-checks/multirole/contract-seal.json --review-profile
  /tmp/statem-verification-checks/multirole/review-profile.json --output
  /tmp/statem-verification-checks/multirole/solver-plan.json`.
  Create the bounded view with `python3
  {self._REMOTE_PROMOTION_GATE.as_posix()} context-view --role
  preflight_reviewer --include /tmp/statem-verification-checks/task.txt --include
  /tmp/statem-verification-checks/multirole/contract-seal.json --include
  /tmp/statem-verification-checks/multirole/review-profile.json --include
  /tmp/statem-verification-checks/multirole/solver-plan.json --output
  /tmp/statem-verification-checks/multirole/preflight-context-view.json`, then
  generate preflight-task.json with the gate's `preflight-task` action and
  initialize it with `statem team init` in the current solve entry.
- Read the current solve entry id from `statem cur --json`, then launch exactly
  one overlapping reviewer with `statem-teamrun-codex-workers --run-id
  {run_id} --state-dir {state_dir} --entry-id <current-solve-entry-id> --cwd
  /app --max-workers 1 --max-rounds 1 --timeout {preflight_timeout}
  --wall-timeout {preflight_wall} --return-slack {preflight_slack}
  --lease-seconds {preflight_lease} --deadline-reserve-seconds 180 --agent-prefix
  preflight --agent-role preflight-reviewer --execution-profile
  read-only-review --model {shlex.quote(self._reviewer_model)}
  --reasoning-effort {shlex.quote(self._preflight_reviewer_reasoning_effort)}
  --no-unified-exec --detach --handle-file {preflight_handle} --json`.
  Continue solver work immediately after launch. Do not start another reviewer.
  The longer lease protects entry ownership across local suspend/resume and
  result submission; it does not increase the worker compute or wall budget.
- Before the initial proposal, join the same handle with
  `statem-teamrun-codex-workers --run-id {run_id} --state-dir {state_dir}
  --entry-id <current-solve-entry-id> --handle-file {preflight_handle}
  --join-handle --join-timeout {preflight_wall} --json`. Record the immutable
  advisory receipt with the gate's `preflight-evidence` action, then advance
  TeamRun to reducing and run `statem team reduce --strategy all-claims-table`.
  Read and address supported findings, but remember this reviewer cannot
  authorize promotion. Consume its compact contract_ledger as hard constraints,
  defeasible claims, probe-required conflicts, and repair implications. Pass
  its candidate-blind acceptance obligations forward without rewriting them.
  The preflight role has execution class contract_language; the post-candidate
  falsifier performs code-semantic and artifact-consumer adjudication against
  the sealed candidate. Pass
  `--preflight-evidence
  /tmp/statem-verification-checks/multirole/preflight-evidence.json` to the
  initial proposal action so the candidate binds exactly that receipt.
- The falsifier must execute the base review template plus every selected
  reviewer.md profile, return ordered stage and profile-check receipts, and
  account for every mandatory practice and protected behavior claim.
- Identity binding, canonical field names, receipt cardinality, coverage
  accounting, and authorization are deterministic gate responsibilities. The
  `review-pre-submit` action fills missing trusted bindings and repairs only an
  unambiguous legacy stage id; any conflict remains a hard failure. The
  falsifier should concentrate on semantic forks, contract basis,
  counterexamples, paired causal attribution, and structured hard quantitative
  gaps.
- Reviewer regressions are blocking only with a supported contract basis and
  paired baseline/candidate evidence. When the task names an exact public
  oracle, version, or normative consumer, both artifacts must also be compared
  to that reference on the same case; the baseline is defeasible evidence, not
  an authority. Candidate-only concerns are residual.
- A validated candidate regression or public-contract drift is revision
  evidence while review budget remains; preserve the live candidate and
  lead-solver context, address supported evidence, and bind a fresh proposal
  and candidate snapshot. When review budget ends without a hard provenance or
  transaction failure, quarantine the exact reviewed snapshot and replay that
  candidate. Roll back only when the reviewed artifact can no longer be safely
  identified or repaired inside the cycle. The review guard permits at most two
  reviews in a cycle.
- Never manually copy or restore /app. Follow only provider activation/restore
  hooks and their verified receipts.
"""

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    "statem-teamrun-codex-workers "
                    f"--run-id {shlex.quote(run_id)} "
                    f"--state-dir {shlex.quote(self._REMOTE_STATE_DIR.as_posix())} "
                    "--entry-id '' --handle-file "
                    "/tmp/statem-verification-checks/multirole/preflight-worker.json "
                    "--cancel-handle --cancel-reason adapter_cleanup --json "
                    ">/dev/null 2>&1 || true"
                ),
                env=self._statem_env(run_id),
            )
        except Exception:
            pass
        agent_statem_dir = (
            PurePosixPath(EnvironmentPaths.agent_dir.as_posix()) / "statem"
        )
        provider_export = agent_statem_dir / "artifact-provider"
        await self.exec_as_agent(
            environment,
            command=(
                f"python3 {shlex.quote(self._REMOTE_ARTIFACT_PROVIDER.as_posix())} "
                "export "
                f"--provider-root {shlex.quote(self._REMOTE_PROVIDER_RECEIPTS.as_posix())} "
                f"--destination {shlex.quote(provider_export.as_posix())} "
                f"--output {shlex.quote((agent_statem_dir / 'artifact-provider-export.json').as_posix())}"
            ),
            env=self._statem_env(run_id),
        )
        enforce_final_state = self._enforce_final_state
        self._enforce_final_state = False
        try:
            await super()._collect_statem_artifacts(environment, context, run_id)
        finally:
            self._enforce_final_state = enforce_final_state

        try:
            await self.exec_as_agent(
                environment,
                command=(
                    "cp -R /tmp/statem-verification-checks/activation "
                    f"{shlex.quote((agent_statem_dir / 'activation').as_posix())} || true"
                ),
                env=self._statem_env(run_id),
            )
        except Exception:
            pass

        current = ((context.metadata or {}).get("statem") or {}).get("current")
        if enforce_final_state and current != self._final_state:
            raise RuntimeError(
                f"statem final state is {current!r}, expected {self._final_state!r}"
            )


class EvidenceDevelopV4p30ExperimentalStatemCodex(
    EvidenceDevelopV4ExperimentalStatemCodex
):
    """Versioned identity for the candidate-blind and information-gain ablation."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p30-exp"


class EvidenceDevelopV4p31ExperimentalStatemCodex(
    EvidenceDevelopV4ExperimentalStatemCodex
):
    """Family-routed failure closure with deadline-feasible recovery cycles."""

    _LOCAL_FAMILY_ROUTER = (
        Path(__file__).resolve().parent
        / "experimental"
        / "develop_family_router.py"
    )
    _LOCAL_FAMILY_CATALOG = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "develop-family-router-v1.yaml"
    )
    _LOCAL_FAILURE_FEEDBACK_GATE = (
        Path(__file__).resolve().parent
        / "experimental"
        / "failure_feedback_gate.py"
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p31-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p31-exp"

    def _verification_check_paths(self) -> list[Path]:
        return [
            *super()._verification_check_paths(),
            self._LOCAL_FAMILY_ROUTER,
            self._LOCAL_FAMILY_CATALOG,
            self._LOCAL_FAILURE_FEEDBACK_GATE,
        ]

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        base = super()._augment_instruction(instruction, run_id, current_context)
        return base.replace(
            "--include\n"
            "  /tmp/statem-verification-checks/multirole/review-profile.json --include\n"
            "  /tmp/statem-verification-checks/multirole/solver-plan.json --output",
            "--include\n"
            "  /tmp/statem-verification-checks/multirole/review-profile.json --include\n"
            "  /tmp/statem-verification-checks/family/family-selection.json --include\n"
            "  /tmp/statem-verification-checks/recovering-develop/retry-brief.json --include\n"
            "  /tmp/statem-verification-checks/multirole/solver-plan.json --output",
        ) + """

Evidence-develop v4p31 controls:
- Treat family-selection.json as host-owned routing. It limits procedural
  practice and retry reserve but cannot weaken or reinterpret the visible task
  contract.
- On a retry cycle, the candidate-blind preflight context includes the immutable
  retry brief. Copy its exact discriminating_check into required_strata of an
  acceptance requirement while preserving all prior obligations. The host
  rejects a candidate whose preflight plan fails this validation delta.
- Classify failures by owner before requesting another cycle. Artifact repairs
  belong to lead_solver, acceptance-plan defects to test_planner, and authority
  conflicts to contract_reviewer. Adapter, host, sealed-acceptance, and
  infrastructure failures must hand off to their owning control rather than
  consuming another task-agent cycle.
- A novel discriminator is necessary but insufficient for retry. The host also
  requires the family-specific full-cycle reserve needed for solve, review,
  replay, receipt closure, and handoff.
"""

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        agent_statem_dir = (
            PurePosixPath(EnvironmentPaths.agent_dir.as_posix()) / "statem"
        )
        try:
            await super()._collect_statem_artifacts(environment, context, run_id)
        finally:
            try:
                await self.exec_as_agent(
                    environment,
                    command=(
                        "cp -R /tmp/statem-verification-checks/family "
                        f"{shlex.quote((agent_statem_dir / 'family').as_posix())} || true"
                    ),
                    env=self._statem_env(run_id),
                )
            except Exception:
                pass


class EvidenceDevelopV4p32ExperimentalStatemCodex(
    EvidenceDevelopV4p31ExperimentalStatemCodex
):
    """Stratum-complete replay with same-state implementation progress."""

    _PROGRESS_RECEIPTS = (
        "multirole/solver-plan.json",
        "multirole/preflight-evidence.json",
        "multirole/candidate-proposal.json",
        "multirole/acceptance-evidence.json",
        "multirole/acceptance-replay.json",
        "multirole/promotion-decision.json",
        "recovering-develop/cycle-ledger.json",
        "recovering-develop/replay-decision.json",
        "recovering-develop/validation-delta-receipt.json",
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p32-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p32-exp"

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        return super()._augment_instruction(
            instruction,
            run_id,
            current_context,
        ) + """

Evidence-develop v4p32 controls:
- Same-node continuation is real progress when the task artifact or a bounded
  milestone receipt changes. The host compares that composite witness before
  consuming a no-progress resume allowance.
- Candidate-blind adapter replay must bind every predeclared required_strata
  value through covered_strata. Requirement-id coverage alone is insufficient.
"""

    async def _session_progress_identity(
        self,
        environment: BaseEnvironment,
        run_id: str,
        current: dict[str, Any],
    ) -> tuple[str, ...]:
        base = await super()._session_progress_identity(environment, run_id, current)
        receipt_paths = [
            f"/tmp/statem-verification-checks/{relative}"
            for relative in self._PROGRESS_RECEIPTS
        ]
        script = "\n".join(
            [
                "import sys",
                "from pathlib import Path",
                "sys.path.insert(0, '/tmp/statem-verification-checks')",
                "from artifact_identity import artifact_progress_identity, file_sha256, stable_sha256",
                f"paths = {receipt_paths!r}",
                "receipts = {path: file_sha256(Path(path)) if Path(path).is_file() else None for path in paths}",
                "print(stable_sha256({'artifact': artifact_progress_identity(Path('/app')), 'receipts': receipts}))",
            ]
        )
        try:
            result = await self.exec_as_agent(
                environment,
                command="python3 -c " + shlex.quote(script),
                env=self._statem_env(run_id),
            )
            witness = (result.stdout or "").strip()
        except Exception:
            witness = "progress-witness-unavailable"
        return (*base, witness)


class EvidenceDevelopV4p33ExperimentalStatemCodex(
    EvidenceDevelopV4p32ExperimentalStatemCodex
):
    """Canonical preflight receipt identifiers before transition gating."""

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p33-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p33-exp"

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        return super()._augment_instruction(
            instruction,
            run_id,
            current_context,
        ) + """

Evidence-develop v4p33 controls:
- Acceptance requirement ids are mechanical receipt keys. The host trims and
  lowercases them before schema validation, rejects canonical collisions, and
  leaves claims, evidence modes, strata, and verdicts unchanged.
"""


class EvidenceDevelopV4p34ExperimentalStatemCodex(
    EvidenceDevelopV4p33ExperimentalStatemCodex
):
    """Deadline-aware review routing before another revision is opened."""

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p34-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p34-exp"

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        return super()._augment_instruction(
            instruction,
            run_id,
            current_context,
        ) + """

Evidence-develop v4p34 controls:
- Before opening another revision and independent review, the host compares the
  selected family's revision reserve with the official remaining deadline.
- When that complete revision cannot finish, keep the reviewed candidate
  isolated and continue through quarantine, final replay, and handoff. Never
  spend the finalization reserve on a partial revision.
"""


class EvidenceDevelopV4p35ExperimentalStatemCodex(
    EvidenceDevelopV4p34ExperimentalStatemCodex
):
    """Candidate-blind semantic obligation closure before promotion."""

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        **kwargs: Any,
    ):
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p35-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p35-exp"

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        return super()._augment_instruction(
            instruction,
            run_id,
            current_context,
        ) + """

Evidence-develop v4p35 controls:
- Every candidate-blind acceptance obligation receives exactly one independent
  reviewer assessment whose evidence provenance matches its immutable mode.
- Missing, mode-incompatible, non-discriminating, unresolved, or falsified
  obligations block promotion and route to revision or deadline-aware
  quarantine; unrelated passing checks cannot close them.
- Multiple plausible objective orderings remain unresolved until visible
  authority or a fixed public population actually distinguishes their outputs.
"""
