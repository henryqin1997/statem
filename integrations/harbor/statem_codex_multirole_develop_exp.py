from __future__ import annotations

import json
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

from integrations.harbor.statem_codex import TeamRunStatemCodex


class MultiRoleDevelopExperimentalStatemCodex(TeamRunStatemCodex):
    """Minimal solver/falsifier StateM experiment with deterministic promotion."""

    _DEFAULT_REMOTE_WORKSPACE_ROOT = PurePosixPath("/app")
    _REMOTE_WORKSPACE_RECEIPT = PurePosixPath(
        "/tmp/statem-verification-checks/workspace-root.json"
    )
    _RESERVED_REMOTE_WORKSPACE_ROOTS = {
        "/",
        "/harbor",
        "/logs",
        "/solution",
        "/tests",
        "/tmp",
    }

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

    def _workspace_root(self) -> PurePosixPath:
        root = getattr(
            self,
            "_remote_workspace_root",
            self._DEFAULT_REMOTE_WORKSPACE_ROOT,
        )
        return root if isinstance(root, PurePosixPath) else PurePosixPath(str(root))

    async def _bind_remote_workspace_root(
        self,
        environment: BaseEnvironment,
    ) -> PurePosixPath:
        result = await self.exec_as_agent(environment, command="pwd -P")
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if len(lines) != 1 or not lines[0].startswith("/"):
            raise RuntimeError("could not bind one absolute default task workspace")
        root = PurePosixPath(lines[0])
        if root.as_posix() in self._RESERVED_REMOTE_WORKSPACE_ROOTS:
            raise RuntimeError(
                f"refusing unsafe default task workspace: {root.as_posix()}"
            )
        self._remote_workspace_root = root
        receipt = {
            "version": 1,
            "kind": "task_workspace_binding",
            "path": root.as_posix(),
            "source": "agent_default_workdir",
            "validated": True,
        }
        await self._write_remote_text(
            environment,
            self._REMOTE_WORKSPACE_RECEIPT.as_posix(),
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        )
        return root

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        state_dir = self._REMOTE_STATE_DIR.as_posix()
        workspace_root = shlex.quote(self._workspace_root().as_posix())
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
  --entry-id <current-entry-id> --cwd {workspace_root} --max-workers 1 --max-rounds 1
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
        self._latest_targeted_preflight_repair_status = ""

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

    _RECEIPT_ONLY_PROVIDER_EXPORT = False

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
        workspace_root = shlex.quote(self._workspace_root().as_posix())
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
  --artifact-root {workspace_root} --expected-receipt
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
  {workspace_root} --max-workers 1 --max-rounds 1 --timeout {preflight_timeout}
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
- Never manually copy or restore {workspace_root}. Follow only provider activation/restore
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
        receipt_only = (
            " --receipt-only" if self._RECEIPT_ONLY_PROVIDER_EXPORT else ""
        )
        await self.exec_as_agent(
            environment,
            command=(
                f"python3 {shlex.quote(self._REMOTE_ARTIFACT_PROVIDER.as_posix())} "
                "export "
                f"--provider-root {shlex.quote(self._REMOTE_PROVIDER_RECEIPTS.as_posix())} "
                f"--destination {shlex.quote(provider_export.as_posix())} "
                f"{receipt_only} "
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
        workspace_root = self._workspace_root().as_posix()
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
                f"print(stable_sha256({{'artifact': artifact_progress_identity(Path({workspace_root!r})), 'receipts': receipts}}))",
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


class EvidenceDevelopV4p36ExperimentalStatemCodex(
    EvidenceDevelopV4p35ExperimentalStatemCodex
):
    """Lifecycle-aware progress for candidate-blind planning and review."""

    _PROGRESS_RECEIPTS = (
        *EvidenceDevelopV4p35ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        "multirole/solver-plan-draft.json",
        "multirole/review-profile-draft.json",
        "multirole/proposal-draft.json",
        "multirole/acceptance-replay-plan-draft.json",
        "multirole/acceptance-evidence-draft.json",
    )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p36-exp"

    def _session_no_progress_limit(self) -> int:
        return 4

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

Evidence-develop v4p36 controls:
- Candidate-blind plan and reviewer-profile revisions are lifecycle progress
  even before they mutate the task artifact or produce a sealed receipt.
- The host permits four consecutive unchanged same-context resumes before
  declaring lifecycle no-progress. The hard eight-resume and task-deadline
  bounds remain unchanged.
- Each resume records only bounded state and progress-change metadata so a
  protocol stop can be attributed without exposing task trajectories.
"""


class EvidenceDevelopV4p37ExperimentalStatemCodex(
    EvidenceDevelopV4p36ExperimentalStatemCodex
):
    """Canonical preflight evidence across the full review lifecycle."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p37-exp"

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

Evidence-develop v4p37 controls:
- The canonical plan_preflight_evidence receipt remains mechanically valid
  across falsifier initialization, acceptance-obligation adjudication, and the
  final promotion decision. Receipt naming cannot discard bound semantic
  evidence or strand the run in the falsify state.
"""


class EvidenceDevelopV4p38ExperimentalStatemCodex(
    EvidenceDevelopV4p37ExperimentalStatemCodex
):
    """Bound same-entry progress to the latest semantic transition blocker."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p38-exp"

    async def _session_progress_identity(
        self,
        environment: BaseEnvironment,
        run_id: str,
        current: dict[str, Any],
    ) -> tuple[str, ...]:
        base = await super()._session_progress_identity(environment, run_id, current)
        script = "\n".join(
            [
                "import hashlib, json, re",
                "from pathlib import Path",
                f"run_id = {run_id!r}",
                "path = Path('/tmp/statem-state/runs') / run_id / 'state.json'",
                "data = json.loads(path.read_text(encoding='utf-8'))",
                "current = str(data.get('current') or '')",
                "entry_id = str(data.get('current_entry_id') or '')",
                "history = data.get('history') if isinstance(data.get('history'), list) else []",
                "start = -1",
                "for index, event in enumerate(history):",
                "    if not isinstance(event, dict):",
                "        continue",
                "    if start < 0 and str(event.get('entry_id') or '') == entry_id and 'node' in event and 'path' in event:",
                "        start = index",
                "latest = None",
                "for event in history[start + 1:]:",
                "    if not isinstance(event, dict) or event.get('event') != 'goto_blocked':",
                "        continue",
                "    if str(event.get('from') or '') != current:",
                "        continue",
                "    failed = []",
                "    for result in event.get('results') or []:",
                "        if not isinstance(result, dict) or result.get('passed') is not False or not result.get('blocking'):",
                "            continue",
                "        output = str(result.get('output') or '').strip().splitlines()[:1]",
                "        summary = output[0] if output else ''",
                "        summary = re.sub(r'\\b[0-9a-fA-F]{64}\\b', '<sha256>', summary)",
                "        summary = re.sub(r'\\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\\b', '<uuid>', summary)",
                "        failed.append({",
                "            'type': result.get('type'),",
                "            'purpose': result.get('purpose'),",
                "            'exit_code': result.get('exit_code'),",
                "            'on_failure': result.get('on_failure'),",
                "            'summary': summary,",
                "        })",
                "    if failed:",
                "        latest = {",
                "            'from': event.get('from'),",
                "            'to': event.get('to'),",
                "            'stage': event.get('stage'),",
                "            'failed': failed,",
                "        }",
                "if latest is not None:",
                "    encoded = json.dumps(latest, sort_keys=True, separators=(',', ':')).encode('utf-8')",
                "    print('blocked:' + hashlib.sha256(encoded).hexdigest())",
            ]
        )
        try:
            result = await self.exec_as_agent(
                environment,
                command="python3 -c " + shlex.quote(script),
                env=self._statem_env(run_id),
            )
            blocker = (result.stdout or "").strip()
        except Exception:
            blocker = ""
        if blocker.startswith("blocked:"):
            return (*base[:2], blocker)
        return base

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

Evidence-develop v4p38 controls:
- Within one StateM entry, the latest blocking-check fingerprint dominates
  draft and artifact churn. Repeating the same semantic blocker consumes the
  bounded no-progress resume allowance; changing the blocker or advancing
  state remains progress.
- Failed validation-delta application removes any prior success receipt before
  returning failure, so stale evidence cannot affect progress or audit tools.
"""


class EvidenceDevelopV4p39ExperimentalStatemCodex(
    EvidenceDevelopV4p38ExperimentalStatemCodex
):
    """Keep matched development cells on the evaluated Codex release."""

    _PINNED_CODEX_VERSION = "0.148.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        requested_version = kwargs.get("version")
        if requested_version not in (None, self._PINNED_CODEX_VERSION):
            raise ValueError(
                "Evidence develop v4p39 requires Codex "
                f"{self._PINNED_CODEX_VERSION}, got {requested_version}"
            )
        kwargs["version"] = self._PINNED_CODEX_VERSION
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p39-exp"


class EvidenceDevelopV4p40ExperimentalStatemCodex(
    EvidenceDevelopV4p39ExperimentalStatemCodex
):
    """Bind deadline-degraded quarantine to the downstream promotion gate."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p40-exp"


class _TransitionFailureFeedbackMixin:
    """Carry bounded transition failures into same-session recovery prompts."""

    _TRANSITION_BLOCKER_DOMINATES_PROGRESS = False
    _LOCAL_TRANSITION_FAILURE_FEEDBACK = (
        Path(__file__).resolve().parent
        / "experimental"
        / "transition_failure_feedback.py"
    )
    _TRANSITION_FAILURE_FEEDBACK = (
        "/tmp/statem-verification-checks/recovering-develop/"
        "transition-failure-feedback.json"
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._latest_transition_failure_summary = ""
        self._latest_transition_failure_owner = ""
        self._latest_transition_failure_action = ""
        self._latest_transition_failure_fingerprint = ""
        super().__init__(*args, **kwargs)

    def _verification_check_paths(self) -> list[Path]:
        return [
            *super()._verification_check_paths(),
            self._LOCAL_TRANSITION_FAILURE_FEEDBACK,
        ]

    async def _session_progress_identity(
        self,
        environment: BaseEnvironment,
        run_id: str,
        current: dict[str, Any],
    ) -> tuple[str, ...]:
        state_path = f"/tmp/statem-state/runs/{run_id}/state.json"
        command = (
            "python3 /tmp/statem-verification-checks/"
            "transition_failure_feedback.py "
            f"--state {shlex.quote(state_path)} "
            f"--output {shlex.quote(self._TRANSITION_FAILURE_FEEDBACK)}"
        )
        self._latest_transition_failure_summary = ""
        self._latest_transition_failure_owner = ""
        self._latest_transition_failure_action = ""
        self._latest_transition_failure_fingerprint = ""
        try:
            result = await self.exec_as_agent(
                environment,
                command=command,
                env=self._statem_env(run_id),
            )
            payload = json.loads((result.stdout or "").strip())
            failed = payload.get("failed_checks") if isinstance(payload, dict) else None
            if isinstance(failed, list):
                summaries = [
                    str(item.get("summary") or "").strip()
                    for item in failed
                    if isinstance(item, dict) and str(item.get("summary") or "").strip()
                ]
                self._latest_transition_failure_summary = "; ".join(summaries)[:1000]
                first = next(
                    (item for item in failed if isinstance(item, dict)),
                    {},
                )
                self._latest_transition_failure_owner = str(
                    first.get("repair_owner") or ""
                ).strip()
                self._latest_transition_failure_action = str(
                    first.get("repair_action") or ""
                ).strip()
                self._latest_transition_failure_fingerprint = str(
                    payload.get("blocker_fingerprint") or ""
                ).strip()
        except Exception:
            self._latest_transition_failure_summary = ""
            self._latest_transition_failure_owner = ""
            self._latest_transition_failure_action = ""
            self._latest_transition_failure_fingerprint = ""
        base = await super()._session_progress_identity(environment, run_id, current)
        if (
            self._TRANSITION_BLOCKER_DOMINATES_PROGRESS
            and self._latest_transition_failure_fingerprint
        ):
            return (
                str(current.get("current") or ""),
                str(current.get("current_entry_id") or ""),
                "blocked:" + self._latest_transition_failure_fingerprint,
            )
        return base

    def _session_resume_prompt(self, current: dict[str, Any]) -> str:
        base = super()._session_resume_prompt(current)
        summary = getattr(self, "_latest_transition_failure_summary", "").strip()
        if not summary:
            return base
        owner = getattr(self, "_latest_transition_failure_owner", "").strip()
        action = getattr(self, "_latest_transition_failure_action", "").strip()
        return (
            base
            + " The host recorded the latest bounded transition failure in "
            + self._TRANSITION_FAILURE_FEEDBACK
            + f": {summary}. Immediate repair owner: {owner or 'transition_check_owner'}. "
            + (f"Required repair: {action} " if action else "")
            + "Repair that exact failed gate before retrying the "
            "transition. Preserve already passing obligations, update the owning "
            "artifact or validation plan, rerun the failed public gate, and do not "
            "repeat an unchanged transition attempt."
        )


class EvidenceDevelopV4p41ExperimentalStatemCodex(
    _TransitionFailureFeedbackMixin,
    EvidenceDevelopV4p40ExperimentalStatemCodex,
):
    """Carry bounded transition failures into same-session recovery prompts."""

    _PROGRESS_RECEIPTS = (
        *EvidenceDevelopV4p40ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        "recovering-develop/transition-failure-feedback.json",
    )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p41-exp"


class EvidenceDevelopV4p42ExperimentalStatemCodex(
    EvidenceDevelopV4p39ExperimentalStatemCodex
):
    """Version the family-scoped public artifact transaction practice."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p42-exp"


class EvidenceDevelopV4p43ExperimentalStatemCodex(
    _TransitionFailureFeedbackMixin,
    EvidenceDevelopV4p42ExperimentalStatemCodex,
):
    """Bound exact transition-gate repair for the artifact practice."""

    _TRANSITION_BLOCKER_DOMINATES_PROGRESS = True
    _PROGRESS_RECEIPTS = (
        *EvidenceDevelopV4p42ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        "recovering-develop/transition-failure-feedback.json",
    )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p43-exp"

    def _session_no_progress_limit(self) -> int:
        # One same-context repair session is enough to distinguish closure from
        # an unchanged gate loop. A changed blocker or state still resets it.
        return 1

    def _codex_stop_hook_payload(self) -> dict[str, Any]:
        payload = super()._codex_stop_hook_payload()
        hook = payload["hooks"]["Stop"][0]["hooks"][0]
        hook["command"] = (
            "STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY=1 " + hook["command"]
        )
        return payload

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

Evidence-develop v4p43 controls:
- A blocked transition is a repairable lifecycle event with an immediate
  owner. When the validation-delta gate fails, the test planner repairs the
  candidate-blind plan from the immutable retry brief; the lead does not
  create another candidate or weaken the gate.
- The latest blocker fingerprint dominates unrelated draft churn. One bounded
  same-context repair session may rerun the failed public gate. If the same
  blocker remains, stop fail-closed as protocol-invalid instead of consuming
  additional review or candidate cycles.
"""


class EvidenceDevelopV4p44ExperimentalStatemCodex(
    EvidenceDevelopV4p43ExperimentalStatemCodex
):
    """Reserve one same-context continuation for a newly blocked transition."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p44-exp"

    def _codex_stop_hook_payload(self) -> dict[str, Any]:
        payload = super()._codex_stop_hook_payload()
        hook = payload["hooks"]["Stop"][0]["hooks"][0]
        hook["command"] = (
            "STATEM_STOP_EXTRA_CONTINUATIONS_AFTER_GOTO_BLOCKED=1 "
            + hook["command"]
        )
        return payload

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

Evidence-develop v4p44 lifecycle control:
- The base entry continuation remains unchanged. If this exact entry records a
  blocked transition, the Stop hook grants one additional same-context
  continuation so the immediate owner can repair and rerun that gate.
- The extra slot is unavailable before a blocked transition and does not reset
  candidate, review, or blocker-fingerprint budgets. A repeated unchanged
  block still fails closed.
"""

class EvidenceDevelopV4p45ExperimentalStatemCodex(
    EvidenceDevelopV4p44ExperimentalStatemCodex
):
    """Atomically commit an authorized append-only preflight repair."""

    _PROGRESS_RECEIPTS = (
        *EvidenceDevelopV4p44ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        "recovering-develop/preflight-evidence.raw.json",
        "recovering-develop/preflight-evidence-repair-draft.json",
        "recovering-develop/preflight-repair-transaction.json",
    )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p45-exp"

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

Evidence-develop v4p45 preflight repair transaction:
- When bounded transition feedback assigns an acceptance-plan gap to the test
  planner, preserve multirole/preflight-evidence.json as immutable reviewer
  evidence. Copy it to recovering-develop/preflight-evidence-repair-draft.json
  and append the retry brief's exact discriminating_check to required_strata
  of exactly one existing requirement. Do not change any other field, order,
  identity, claim, evidence mode, public surface, rationale, independence
  basis, or support dimension.
- Commit only through `failure_feedback_gate.py commit-preflight-repair` with
  the retry brief, entry-scoped transition feedback, canonical preflight,
  repair draft, immutable raw-backup, and transaction-receipt paths. The host
  requires a test-planner acceptance-plan-gap owner, validates the append-only
  delta, and atomically replaces canonical evidence; invalid drafts leave it
  unchanged.
  Run `python3 /tmp/statem-verification-checks/failure_feedback_gate.py
  commit-preflight-repair --brief
  /tmp/statem-verification-checks/recovering-develop/retry-brief.json
  --canonical-preflight
  /tmp/statem-verification-checks/multirole/preflight-evidence.json
  --repair-draft
  /tmp/statem-verification-checks/recovering-develop/preflight-evidence-repair-draft.json
  --raw-backup
  /tmp/statem-verification-checks/recovering-develop/preflight-evidence.raw.json
  --transition-feedback
  /tmp/statem-verification-checks/recovering-develop/transition-failure-feedback.json
  --output
  /tmp/statem-verification-checks/recovering-develop/preflight-repair-transaction.json`.
- After a committed transaction, rerun the existing validate-preflight gate
  against the canonical path before retrying the blocked transition. Do not
  spend another candidate or review cycle on this planner-owned repair.
"""


class EvidenceDevelopV4p46ExperimentalStatemCodex(
    EvidenceDevelopV4p45ExperimentalStatemCodex
):
    """Bind the v4p46 host schema repair to an unambiguous agent identity."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p46-exp"


class EvidenceDevelopV4p47ExperimentalStatemCodex(
    EvidenceDevelopV4p46ExperimentalStatemCodex
):
    """Bind append-only derived preflight evidence to its raw TeamRun source."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p47-exp"


class EvidenceDevelopV4p48ExperimentalStatemCodex(
    EvidenceDevelopV4p47ExperimentalStatemCodex
):
    """Quarantine ordered-composition review behind a distinct identity."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p48-exp"


class EvidenceDevelopV4p49ExperimentalStatemCodex(
    EvidenceDevelopV4p48ExperimentalStatemCodex
):
    """Close public adapter-obligation gaps through bounded recovery."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p49-exp"


class EvidenceDevelopV4p50ExperimentalStatemCodex(
    EvidenceDevelopV4p49ExperimentalStatemCodex
):
    """Physically exclude quarantined reviewer-practice candidates."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p50-exp"


class EvidenceDevelopV4p51ExperimentalStatemCodex(
    EvidenceDevelopV4p50ExperimentalStatemCodex
):
    """Bind candidate-blind support coverage to explicit selection and gaps."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p51-exp"

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

Evidence-develop v4p51 support-coverage control:
- Candidate-blind acceptance requirements bind their pre-candidate population
  selection basis and known uncovered regions. Do not present observed values,
  random samples, or a generic category label as exhaustive support.
- When a public oracle accepts a finite or compactly enumerable categorical
  domain, exercise that domain exhaustively when feasible and retain
  exceptional categories plus the fallback class. Missing or unknown regions
  remain explicit review obligations rather than silently disappearing into a
  larger numeric population.
"""


class EvidenceDevelopV4p52ExperimentalStatemCodex(
    EvidenceDevelopV4p51ExperimentalStatemCodex
):
    """Bind filesystem transactions to the validated task workspace."""

    _RECEIPT_ONLY_PROVIDER_EXPORT = True

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
            / "frontier-bench-agent-evidence-develop-v4p52-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p52-exp"

    def _statem_env(self, run_id: str) -> dict[str, str]:
        env = super()._statem_env(run_id)
        env["STATEM_ARTIFACT_ROOT"] = self._workspace_root().as_posix()
        return env

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await self._bind_remote_workspace_root(environment)
        await super().run(instruction, environment, context)


class EvidenceDevelopV4p53ExperimentalStatemCodex(
    EvidenceDevelopV4p52ExperimentalStatemCodex
):
    """Mechanically carry a retry discriminator into its named requirement."""

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
            / "frontier-bench-agent-evidence-develop-v4p53-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p53-exp"

    async def _attempt_targeted_preflight_repair(
        self,
        environment: BaseEnvironment,
        run_id: str,
    ) -> None:
        self._latest_targeted_preflight_repair_status = ""
        if (
            getattr(self, "_latest_transition_failure_owner", "")
            != "test_planner"
            or not getattr(self, "_latest_transition_failure_fingerprint", "")
        ):
            return
        try:
            result = await self.exec_as_agent(
                environment,
                command=(
                    "python3 /tmp/statem-verification-checks/"
                    "failure_feedback_gate.py commit-targeted-preflight-repair"
                ),
                env=self._statem_env(run_id),
            )
            payload = json.loads((result.stdout or "").strip())
            if (
                not isinstance(payload, dict)
                or payload.get("kind")
                != "canonical_preflight_repair_transaction"
                or payload.get("status") not in {"committed", "already_committed"}
            ):
                raise ValueError("targeted repair command returned an invalid receipt")
            self._latest_targeted_preflight_repair_status = str(payload["status"])
        except Exception:
            self._latest_targeted_preflight_repair_status = "failed"

    async def _session_progress_identity(
        self,
        environment: BaseEnvironment,
        run_id: str,
        current: dict[str, Any],
    ) -> tuple[str, ...]:
        identity = await super()._session_progress_identity(
            environment,
            run_id,
            current,
        )
        await self._attempt_targeted_preflight_repair(environment, run_id)
        return identity

    def _session_resume_prompt(self, current: dict[str, Any]) -> str:
        prompt = super()._session_resume_prompt(current)
        status = getattr(self, "_latest_targeted_preflight_repair_status", "")
        if status in {"committed", "already_committed"}:
            return (
                prompt
                + " The host mechanically committed the targeted append-only "
                "preflight repair. Update any adapter-replay plan needed to "
                "execute the newly effective stratum, then rerun the ordinary "
                "gates; do not rewrite reviewer evidence."
            )
        if status == "failed":
            return (
                prompt
                + " The host declined the targeted preflight transaction. "
                "Inspect the bounded retry brief and transition receipt; fix "
                "only an explicit target or evidence conflict and do not infer "
                "a replacement requirement."
            )
        return prompt

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

Evidence-develop v4p53 targeted validation-delta control:
- Every recoverable validation delta names exactly one existing candidate-blind
  acceptance requirement as target_requirement_id. The host validates that
  identity against the bound preflight receipt before authorizing another
  cycle; it never infers a target from prose.
- If transition feedback proves that the retry discriminator is absent and
  assigns the gap to test_planner, the host automatically invokes
  `failure_feedback_gate.py commit-targeted-preflight-repair`. It derives the
  append-only draft itself, preserves immutable raw TeamRun evidence, appends only the exact
  discriminator to the named requirement, and commits atomically. Missing,
  unknown, duplicate, conflicting, or already-mutated evidence remains a hard
  failure. Do not author or copy a repair draft.
- After the transaction, update the candidate acceptance replay plan when the
  targeted requirement uses adapter_replay, so every effective required
  stratum is actually executed. Rerun the ordinary acceptance replay,
  require-preflight, and validation-delta gates; a receipt-only append is not
  evidence that the new check ran.
"""


class EvidenceDevelopV4p54ExperimentalStatemCodex(
    EvidenceDevelopV4p53ExperimentalStatemCodex
):
    """Expose solver obligations and close candidate-blind plan revision."""

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
            / "frontier-bench-agent-evidence-develop-v4p54-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p54-exp"

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

Evidence-develop v4p54 solver-obligation and plan-resolution control:
- The host projects mandatory common practices, primary profile checks, and
  compact secondary profile scope into solver-obligations.json. Cover every
  projected id exactly once in solver-plan obligation_coverage. This gives the
  implementer the constraints it must satisfy without disclosing reviewer-only
  counterexample priorities or verdict calibration.
- The v4p54 plan command supersedes the earlier plan command and adds
  `--solver-obligations
  /tmp/statem-verification-checks/multirole/solver-obligations.json`. Include
  solver-obligations.json in the preflight context view, and add the same
  `--solver-obligations` argument to both preflight-task and
  preflight-evidence actions.
- If candidate-blind preflight returns revise_plan, it is not merely advisory
  prose. Before proposal, write a bounded preflight-resolution-draft.json that
  revises at least one named plan section and addresses every immutable issue
  id. The host validates and records preflight-resolution.json. The candidate
  proposal must bind both the original plan and that resolution receipt.
- A ready preflight needs no solver-authored resolution draft; the host records
  a not_required receipt. Final semantic review remains independent and retains
  sole evidence-based promotion recommendation authority.
- Record the receipt with `multirole_promotion_gate.py resolve-preflight
  --draft /tmp/statem-verification-checks/multirole/preflight-resolution-draft.json
  --plan /tmp/statem-verification-checks/multirole/solver-plan.json
  --preflight-evidence
  /tmp/statem-verification-checks/multirole/preflight-evidence.json
  --solver-obligations
  /tmp/statem-verification-checks/multirole/solver-obligations.json`. The draft
  path may be absent only for a ready verdict. Pass solver-plan.json and
  preflight-resolution.json to both proposal and require-preflight actions.
"""


class EvidenceDevelopV4p55ExperimentalStatemCodex(
    EvidenceDevelopV4p54ExperimentalStatemCodex
):
    """Make solver practices actionable and attribute reviewer receipt failures."""

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
            / "frontier-bench-agent-evidence-develop-v4p55-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p55-exp"

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

Evidence-develop v4p55 role-boundary control:
- Every solver obligation now carries invariant, required_action, and self_check.
  Use these fields as implementation and self-verification requirements; binding
  an id without performing its action is incomplete. Reviewer-only
  counterexample ordering, adversarial probe selection, and verdict calibration
  remain excluded.
- The final reviewer assignment declares the exact bound for every assessment
  text field. A mechanically invalid assessment is owned by reviewer receipt
  expression and never proves a candidate defect. The deterministic gate remains
  fail-closed and never truncates or rewrites semantic reviewer evidence.
"""


class EvidenceDevelopV4p56ExperimentalStatemCodex(
    EvidenceDevelopV4p55ExperimentalStatemCodex
):
    """Separate promotion, diagnostic replay, and benchmark submission."""

    _LOCAL_SUBMISSION_ELIGIBILITY_GATE = (
        Path(__file__).resolve().parent
        / "experimental"
        / "submission_eligibility_gate.py"
    )
    _REMOTE_SUBMISSION_RECEIPTS = PurePosixPath(
        "/tmp/statem-verification-checks/submission"
    )
    _SUBMISSION_POLICIES = {"strict_review", "deadline_best_validated"}
    _PROGRESS_RECEIPTS = (
        *EvidenceDevelopV4p55ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        "submission/submission-eligibility.json",
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        submission_policy: str = "deadline_best_validated",
        **kwargs: Any,
    ):
        if submission_policy not in self._SUBMISSION_POLICIES:
            raise ValueError(
                f"unsupported submission policy: {submission_policy}"
            )
        repo_root = Path(__file__).resolve().parents[2]
        runbook = (
            repo_root
            / "examples"
            / "frontier-bench-agent-evidence-develop-v4p56-exp.yaml"
        )
        self._submission_policy = submission_policy
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p56-exp"

    def _verification_check_paths(self) -> list[Path]:
        return [
            *super()._verification_check_paths(),
            self._LOCAL_SUBMISSION_ELIGIBILITY_GATE,
        ]

    def _statem_env(self, run_id: str) -> dict[str, str]:
        env = super()._statem_env(run_id)
        env["STATEM_SUBMISSION_POLICY"] = self._submission_policy
        return env

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

Evidence-develop v4p56 submission-eligibility control:
- Promotion authorization, diagnostic replay eligibility, and benchmark
  submission eligibility are separate host decisions. The solver and reviewer
  do not choose the final submission target.
- A quarantined candidate with validated negative evidence is diagnostic-only;
  the host restores the immutable baseline before handoff. A quarantined
  candidate with only advisory uncertainty may remain the evaluation target
  under the deadline-best-validated policy only after candidate-bound public
  replay passes.
- Baseline fallback preserves the rejected candidate, receipts, and causal
  evidence. It is a submission transaction, not a claim that the baseline is
  semantically correct and not permission to erase or rewrite review evidence.
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
                        f"cp -R {shlex.quote(self._REMOTE_SUBMISSION_RECEIPTS.as_posix())} "
                        f"{shlex.quote((agent_statem_dir / 'submission').as_posix())} || true"
                    ),
                    env=self._statem_env(run_id),
                )
            except Exception:
                pass


class EvidenceDevelopV4p57ExperimentalStatemCodex(
    EvidenceDevelopV4p56ExperimentalStatemCodex
):
    """Correct promotion receipt revision ownership without changing topology."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p57-exp"


class EvidenceDevelopV4p59ExperimentalStatemCodex(
    EvidenceDevelopV4p57ExperimentalStatemCodex
):
    """Separate bounded acceptance from generalization evidence authority."""

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
            / "frontier-bench-agent-evidence-develop-v4p59-exp.yaml"
        )
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-evidence-develop-v4p59-exp"

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

Evidence-develop v4p59 evidence-scope control:
- Candidate-blind acceptance obligations distinguish bounded public acceptance
  from claims about unseen populations or unresolved semantic forks.
- Training/public fit and bounded generated examples cannot alone authorize a
  generalization claim. The reviewer must bind held-out, normative, or
  discriminating analytic authority and disposition every predeclared
  uncovered region; otherwise the host safely routes to revision or quarantine.
"""
