from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from integrations.harbor.experimental import failure_feedback_gate
from integrations.harbor.experimental.failure_feedback_gate import (
    build_targeted_preflight_repair,
    commit_preflight_repair,
    commit_targeted_preflight_repair,
    prepare_retry_brief,
    validate_preflight_delta,
    validate_preflight_repair,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p45ExperimentalStatemCodex,
    EvidenceDevelopV4p46ExperimentalStatemCodex,
    EvidenceDevelopV4p47ExperimentalStatemCodex,
    EvidenceDevelopV4p48ExperimentalStatemCodex,
    EvidenceDevelopV4p49ExperimentalStatemCodex,
    EvidenceDevelopV4p50ExperimentalStatemCodex,
    EvidenceDevelopV4p51ExperimentalStatemCodex,
    EvidenceDevelopV4p52ExperimentalStatemCodex,
    EvidenceDevelopV4p53ExperimentalStatemCodex,
)
from integrations.harbor.experimental.recovering_develop_guard import (
    _normalize_validation_delta,
    _validate_target_requirement,
    _validate_replay_draft,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4p35-exp.yaml"
RUNBOOK_V4P52 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p52-exp.yaml"
RUNBOOK_V4P53 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p53-exp.yaml"


class PreflightRepairTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _replay(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "recovering_develop_replay_decision",
            "action": "retry",
            "failure_ownership": {
                "failure_class": "acceptance_plan_gap",
                "owner_role": "test_planner",
                "observed_failure": "public replay exposed a boundary mismatch",
                "causal_hypothesis": "the plan omitted the discriminating case",
                "repair_action": "append the exact discriminating case",
                "required_validation_update": "bind the prior failure",
                "confidence": "high",
            },
            "validation_delta": {
                "action": "append_regression",
                "discriminating_check": (
                    "replay literal and encoded boundary pairs on the public consumer"
                ),
                "success_interpretation": "only the contract-defined form is rejected",
                "failure_interpretation": "the repair still conflates the forms",
                "preserves_prior_obligations": True,
                "superseded_check_ids": [],
                "rationale": "bind the prior failure to independent acceptance",
            },
        }

    def _preflight(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "run_id": "repair-test",
            "node": "solve",
            "entry_id": "solve-2",
            "producer": "preflight_reviewer",
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "contract_surface",
                        "claim": "preserve the visible contract",
                        "evidence_mode": "public_probe",
                        "public_surface": "callable",
                        "rationale": "bind the public behavior",
                        "independence_basis": "candidate_blind",
                        "support_dimensions": ["behavior"],
                        "required_strata": ["baseline", "candidate"],
                        "selection_basis": "the visible callable contract",
                        "uncovered_regions": ["none"],
                    },
                    {
                        "requirement_id": "consumer_replay",
                        "claim": "exercise the exact consumer",
                        "evidence_mode": "adapter_replay",
                        "public_surface": "consumer",
                        "rationale": "bind construction and use",
                        "independence_basis": "candidate_blind",
                        "support_dimensions": ["cold", "warm"],
                        "required_strata": ["incremental", "bulk"],
                        "selection_basis": "the public consumer construction paths",
                        "uncovered_regions": ["none"],
                    },
                ]
            },
        }

    def _targeted_replay(self, target: str = "consumer_replay") -> dict[str, object]:
        replay = self._replay()
        replay["validation_delta"]["target_requirement_id"] = target
        return replay

    def _transition_feedback(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "transition_failure_feedback",
            "entry_id": "solve-2",
            "current_state": "solve",
            "target_state": "falsify",
            "stage": "before_transfer",
            "blocker_fingerprint": "a" * 64,
            "repeat_count": 1,
            "repair_budget_exhausted": False,
            "failed_checks": [
                {
                    "failure_class": "acceptance_plan_gap",
                    "repair_owner": "test_planner",
                    "summary": "the exact retry discriminator is absent",
                }
            ],
        }

    def _paths(self) -> dict[str, Path]:
        return {
            name: self.root / f"{name}.json"
            for name in (
                "brief",
                "canonical",
                "draft",
                "raw",
                "transition",
                "receipt",
            )
        }

    def _write_transaction_inputs(
        self,
        *,
        brief: dict[str, object],
        original: dict[str, object],
        draft: dict[str, object],
    ) -> dict[str, Path]:
        paths = self._paths()
        for name, value in (
            ("brief", brief),
            ("canonical", original),
            ("draft", draft),
            ("transition", self._transition_feedback()),
        ):
            paths[name].write_text(json.dumps(value), encoding="utf-8")
        return paths

    def test_commits_exact_append_and_is_idempotent(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        check = replay["validation_delta"]["discriminating_check"]
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(check)
        paths = self._write_transaction_inputs(
            brief=brief,
            original=original,
            draft=draft,
        )

        receipt = commit_preflight_repair(
            brief_path=paths["brief"],
            canonical_path=paths["canonical"],
            draft_path=paths["draft"],
            raw_backup_path=paths["raw"],
            transition_feedback_path=paths["transition"],
            receipt_path=paths["receipt"],
        )

        self.assertEqual(receipt["status"], "committed")
        self.assertEqual(receipt["requirement_id"], "consumer_replay")
        self.assertEqual(json.loads(paths["raw"].read_text()), original)
        self.assertEqual(json.loads(paths["canonical"].read_text()), draft)
        self.assertTrue(
            validate_preflight_delta(brief=brief, preflight_evidence=draft)["applied"]
        )

        repeated = commit_preflight_repair(
            brief_path=paths["brief"],
            canonical_path=paths["canonical"],
            draft_path=paths["draft"],
            raw_backup_path=paths["raw"],
            transition_feedback_path=paths["transition"],
            receipt_path=paths["receipt"],
        )
        self.assertEqual(repeated["status"], "already_committed")
        self.assertEqual(json.loads(paths["raw"].read_text()), original)
        self.assertEqual(json.loads(paths["canonical"].read_text()), draft)

    def test_rejects_semantic_rewrite_without_mutation(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        draft["acceptance_plan"]["requirements"][0]["claim"] = "weakened claim"
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(
            replay["validation_delta"]["discriminating_check"]
        )
        paths = self._write_transaction_inputs(
            brief=brief,
            original=original,
            draft=draft,
        )

        with self.assertRaisesRegex(ValueError, "outside the authorized append"):
            commit_preflight_repair(
                brief_path=paths["brief"],
                canonical_path=paths["canonical"],
                draft_path=paths["draft"],
                raw_backup_path=paths["raw"],
                transition_feedback_path=paths["transition"],
                receipt_path=paths["receipt"],
            )
        self.assertEqual(json.loads(paths["canonical"].read_text()), original)
        self.assertFalse(paths["raw"].exists())
        self.assertFalse(paths["receipt"].exists())

    def test_rejects_multiple_requirement_changes(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        check = replay["validation_delta"]["discriminating_check"]
        draft["acceptance_plan"]["requirements"][0]["required_strata"].append(check)
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(check)
        with self.assertRaisesRegex(ValueError, "exactly one requirement"):
            validate_preflight_repair(
                brief=brief,
                transition_feedback=self._transition_feedback(),
                original=original,
                draft=draft,
            )

    def test_rejects_non_planner_or_cross_entry_transition_feedback(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(
            replay["validation_delta"]["discriminating_check"]
        )
        feedback = self._transition_feedback()
        feedback["failed_checks"][0]["repair_owner"] = "lead_solver"
        with self.assertRaisesRegex(ValueError, "test-planner"):
            validate_preflight_repair(
                brief=brief,
                transition_feedback=feedback,
                original=original,
                draft=draft,
            )

        feedback = self._transition_feedback()
        feedback["entry_id"] = "another-entry"
        with self.assertRaisesRegex(ValueError, "entry must match"):
            validate_preflight_repair(
                brief=brief,
                transition_feedback=feedback,
                original=original,
                draft=draft,
            )

    def test_rejects_unbound_retry_owner_or_blocker_fingerprint(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(
            replay["validation_delta"]["discriminating_check"]
        )

        wrong_owner = copy.deepcopy(brief)
        wrong_owner["failure_ownership"]["owner_role"] = "lead_solver"
        with self.assertRaisesRegex(ValueError, "planner-owned"):
            validate_preflight_repair(
                brief=wrong_owner,
                transition_feedback=self._transition_feedback(),
                original=original,
                draft=draft,
            )

        feedback = self._transition_feedback()
        feedback["blocker_fingerprint"] = "not-a-sha256"
        with self.assertRaisesRegex(ValueError, "SHA-256 blocker fingerprint"):
            validate_preflight_repair(
                brief=brief,
                transition_feedback=feedback,
                original=original,
                draft=draft,
            )

    def test_write_failure_restores_canonical_and_removes_partial_files(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        draft = copy.deepcopy(original)
        draft["acceptance_plan"]["requirements"][1]["required_strata"].append(
            replay["validation_delta"]["discriminating_check"]
        )
        paths = self._write_transaction_inputs(
            brief=brief,
            original=original,
            draft=draft,
        )
        atomic_write = failure_feedback_gate._write_json_atomic

        def fail_receipt(path: Path, payload: dict[str, object]) -> None:
            if path == paths["receipt"]:
                raise OSError("simulated receipt failure")
            atomic_write(path, payload)

        with patch.object(
            failure_feedback_gate,
            "_write_json_atomic",
            side_effect=fail_receipt,
        ):
            with self.assertRaisesRegex(OSError, "simulated receipt failure"):
                commit_preflight_repair(
                    brief_path=paths["brief"],
                    canonical_path=paths["canonical"],
                    draft_path=paths["draft"],
                    raw_backup_path=paths["raw"],
                    transition_feedback_path=paths["transition"],
                    receipt_path=paths["receipt"],
                )

        self.assertEqual(json.loads(paths["canonical"].read_text()), original)
        self.assertFalse(paths["raw"].exists())
        self.assertFalse(paths["receipt"].exists())

    def test_targeted_repair_builds_and_commits_exact_append_idempotently(self) -> None:
        replay = self._targeted_replay()
        brief = prepare_retry_brief(replay)
        original = self._preflight()
        expected = build_targeted_preflight_repair(brief=brief, original=original)
        paths = self._paths()
        for name, value in (
            ("brief", brief),
            ("canonical", original),
            ("transition", self._transition_feedback()),
        ):
            paths[name].write_text(json.dumps(value), encoding="utf-8")

        receipt = commit_targeted_preflight_repair(
            brief_path=paths["brief"],
            canonical_path=paths["canonical"],
            raw_backup_path=paths["raw"],
            transition_feedback_path=paths["transition"],
            receipt_path=paths["receipt"],
        )

        self.assertEqual(receipt["status"], "committed")
        self.assertEqual(receipt["requirement_id"], "consumer_replay")
        self.assertEqual(json.loads(paths["raw"].read_text()), original)
        self.assertEqual(json.loads(paths["canonical"].read_text()), expected)
        self.assertTrue(
            validate_preflight_delta(brief=brief, preflight_evidence=expected)["applied"]
        )

        repeated = commit_targeted_preflight_repair(
            brief_path=paths["brief"],
            canonical_path=paths["canonical"],
            raw_backup_path=paths["raw"],
            transition_feedback_path=paths["transition"],
            receipt_path=paths["receipt"],
        )
        self.assertEqual(repeated["status"], "already_committed")
        self.assertEqual(json.loads(paths["canonical"].read_text()), expected)

    def test_targeted_repair_rejects_missing_unknown_and_duplicate_targets(self) -> None:
        original = self._preflight()
        missing = prepare_retry_brief(self._replay())
        with self.assertRaisesRegex(ValueError, "requires target_requirement_id"):
            build_targeted_preflight_repair(brief=missing, original=original)

        unknown = prepare_retry_brief(self._targeted_replay("unknown_requirement"))
        with self.assertRaisesRegex(ValueError, "not in the canonical preflight"):
            build_targeted_preflight_repair(brief=unknown, original=original)

        duplicate = copy.deepcopy(original)
        duplicate["acceptance_plan"]["requirements"][1]["requirement_id"] = (
            "contract_surface"
        )
        brief = prepare_retry_brief(self._targeted_replay("contract_surface"))
        with self.assertRaisesRegex(ValueError, "duplicate requirement identities"):
            build_targeted_preflight_repair(brief=brief, original=duplicate)

    def test_targeted_validation_rejects_cross_requirement_binding(self) -> None:
        brief = prepare_retry_brief(self._targeted_replay("consumer_replay"))
        wrong = self._preflight()
        check = brief["validation_delta"]["discriminating_check"]
        wrong["acceptance_plan"]["requirements"][0]["required_strata"].append(check)
        with self.assertRaisesRegex(ValueError, "other than target_requirement_id"):
            validate_preflight_delta(brief=brief, preflight_evidence=wrong)

    def test_targeted_delta_schema_and_bound_plan_are_fail_closed(self) -> None:
        delta = self._targeted_replay()["validation_delta"]
        normalized = _normalize_validation_delta(
            delta,
            require_target_requirement=True,
        )
        self.assertEqual(normalized["target_requirement_id"], "consumer_replay")
        with self.assertRaisesRegex(ValueError, "without target_requirement_id"):
            _normalize_validation_delta(delta)
        missing = copy.deepcopy(delta)
        missing.pop("target_requirement_id")
        with self.assertRaisesRegex(ValueError, "plus target_requirement_id"):
            _normalize_validation_delta(missing, require_target_requirement=True)
        with self.assertRaisesRegex(ValueError, "not in the bound preflight plan"):
            _validate_target_requirement(
                preflight_evidence=self._preflight(),
                validation_delta={**delta, "target_requirement_id": "unknown"},
            )

    def test_recoverable_replay_requires_target_only_under_v4p53_gate(self) -> None:
        replay = self._targeted_replay()
        draft = {
            "status": "recoverable_failure",
            "evidence": ["public replay exposed a boundary mismatch"],
            "residual_risk": [],
            "next_gap": "append the exact discriminating case",
            "failure_ownership": replay["failure_ownership"],
            "validation_delta": replay["validation_delta"],
            "hard_gap_resolutions": [],
        }
        _validate_replay_draft(
            draft,
            require_failure_closure=True,
            require_targeted_validation_delta=True,
        )
        old_schema = copy.deepcopy(draft)
        old_schema["validation_delta"].pop("target_requirement_id")
        with self.assertRaisesRegex(ValueError, "plus target_requirement_id"):
            _validate_replay_draft(
                old_schema,
                require_failure_closure=True,
                require_targeted_validation_delta=True,
            )
        _validate_replay_draft(
            old_schema,
            require_failure_closure=True,
            require_targeted_validation_delta=False,
        )

    def test_adapter_exposes_atomic_transaction_without_new_runbook(self) -> None:
        agent = EvidenceDevelopV4p45ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p45ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600

        instruction = agent._augment_instruction("task", "run", "context")

        self.assertIn("commit-preflight-repair", instruction)
        self.assertIn("preflight-evidence-repair-draft.json", instruction)
        self.assertIn("preflight-evidence.raw.json", instruction)
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p45-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertIn(
            "recovering-develop/preflight-repair-transaction.json",
            agent._PROGRESS_RECEIPTS,
        )

    def test_v4p46_identity_inherits_transaction_without_runbook_change(self) -> None:
        agent = EvidenceDevelopV4p46ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p46ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p45ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p45ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p46-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(
            agent._PROGRESS_RECEIPTS,
            EvidenceDevelopV4p45ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        )
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["agent"], agent.name())
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p47_identity_inherits_controls_without_runbook_change(self) -> None:
        agent = EvidenceDevelopV4p47ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p47ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p46ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p46ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p47-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(agent._PROGRESS_RECEIPTS, prior._PROGRESS_RECEIPTS)
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["agent"], agent.name())
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p48_identity_isolates_profile_candidate_without_runbook_change(self) -> None:
        agent = EvidenceDevelopV4p48ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p48ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p47ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p47ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p48-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(agent._PROGRESS_RECEIPTS, prior._PROGRESS_RECEIPTS)
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["agent"], agent.name())
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p49_identity_isolates_acceptance_recovery_without_runbook_change(self) -> None:
        agent = EvidenceDevelopV4p49ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p49ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p48ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p48ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p49-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(agent._PROGRESS_RECEIPTS, prior._PROGRESS_RECEIPTS)
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["agent"], agent.name())
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p50_identity_isolates_quarantined_practice_exclusion(self) -> None:
        agent = EvidenceDevelopV4p50ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p50ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p49ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p49ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p50-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(agent._PROGRESS_RECEIPTS, prior._PROGRESS_RECEIPTS)
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p51_identity_isolates_support_coverage_control(self) -> None:
        agent = EvidenceDevelopV4p51ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p51ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        prior = EvidenceDevelopV4p50ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p50ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p51-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(agent._PROGRESS_RECEIPTS, prior._PROGRESS_RECEIPTS)
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["files"], prior_manifest["files"])
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p52_identity_binds_a_distinct_workspace_aware_runbook(self) -> None:
        agent = EvidenceDevelopV4p52ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p52ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK_V4P52
        prior = EvidenceDevelopV4p51ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p51ExperimentalStatemCodex
        )
        prior._statem_source_dir = REPO
        prior._runbook_path = RUNBOOK

        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p52-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P52)
        self.assertTrue(agent._RECEIPT_ONLY_PROVIDER_EXPORT)
        self.assertEqual(agent._workspace_root().as_posix(), "/app")
        self.assertFalse(prior._RECEIPT_ONLY_PROVIDER_EXPORT)
        self.assertEqual(prior._workspace_root().as_posix(), "/app")
        manifest = agent._build_source_manifest()
        prior_manifest = prior._build_source_manifest()
        self.assertEqual(manifest["file_count"], prior_manifest["file_count"])
        self.assertEqual(
            manifest["runbook"],
            "examples/frontier-bench-agent-evidence-develop-v4p52-exp.yaml",
        )
        self.assertNotEqual(
            manifest["manifest_sha256"], prior_manifest["manifest_sha256"]
        )

    def test_v4p52_runbook_strictly_binds_transaction_hooks_to_workspace(self) -> None:
        payload = validate_spec(str(RUNBOOK_V4P52), strict=True)
        self.assertTrue(payload["ok"])
        text = RUNBOOK_V4P52.read_text(encoding="utf-8")
        self.assertIn("STATEM_ARTIFACT_ROOT", text)
        self.assertIn("workspace-root.json", text)
        self.assertNotIn("--artifact-root /app", text)
        self.assertNotIn("--cwd /app", text)

    def test_v4p52_binds_one_safe_default_workspace_and_receipt(self) -> None:
        agent = EvidenceDevelopV4p52ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p52ExperimentalStatemCodex
        )
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(stdout="/workspace\n")
        )
        agent._write_remote_text = AsyncMock()

        root = asyncio.run(agent._bind_remote_workspace_root(object()))

        self.assertEqual(root.as_posix(), "/workspace")
        self.assertEqual(
            agent._statem_env("run-1")["STATEM_ARTIFACT_ROOT"],
            "/workspace",
        )
        receipt = json.loads(agent._write_remote_text.await_args.args[2])
        self.assertEqual(receipt["kind"], "task_workspace_binding")
        self.assertEqual(receipt["path"], "/workspace")
        self.assertTrue(receipt["validated"])

    def test_v4p52_rejects_root_as_a_transaction_workspace(self) -> None:
        agent = EvidenceDevelopV4p52ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p52ExperimentalStatemCodex
        )
        agent.exec_as_agent = AsyncMock(return_value=SimpleNamespace(stdout="/\n"))
        agent._write_remote_text = AsyncMock()

        with self.assertRaisesRegex(RuntimeError, "unsafe default task workspace"):
            asyncio.run(agent._bind_remote_workspace_root(object()))
        agent._write_remote_text.assert_not_awaited()

    def test_v4p53_identity_binds_targeted_delta_runbook_and_host_command(self) -> None:
        agent = EvidenceDevelopV4p53ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p53ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK_V4P53
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600

        instruction = agent._augment_instruction("task", "run", "context")
        payload = validate_spec(str(RUNBOOK_V4P53), strict=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p53-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P53)
        self.assertIn("commit-targeted-preflight-repair", instruction)
        self.assertIn("target_requirement_id", instruction)
        self.assertIn("Do not author or copy a repair draft", instruction)
        text = RUNBOOK_V4P53.read_text(encoding="utf-8")
        self.assertIn("--require-targeted-validation-delta", text)
        self.assertIn("target_requirement_id", text)

    def test_v4p53_host_attempts_only_planner_owned_targeted_repair(self) -> None:
        agent = EvidenceDevelopV4p53ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p53ExperimentalStatemCodex
        )
        agent._latest_transition_failure_owner = "test_planner"
        agent._latest_transition_failure_fingerprint = "a" * 64
        agent._statem_env = lambda run_id: {"STATEM_RUN_ID": run_id}
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(
                stdout=json.dumps(
                    {
                        "kind": "canonical_preflight_repair_transaction",
                        "status": "committed",
                    }
                )
            )
        )

        asyncio.run(agent._attempt_targeted_preflight_repair(object(), "run-1"))

        self.assertEqual(agent._latest_targeted_preflight_repair_status, "committed")
        self.assertIn(
            "commit-targeted-preflight-repair",
            agent.exec_as_agent.await_args.kwargs["command"],
        )

        agent._latest_transition_failure_owner = "lead_solver"
        agent.exec_as_agent.reset_mock()
        asyncio.run(agent._attempt_targeted_preflight_repair(object(), "run-1"))
        agent.exec_as_agent.assert_not_awaited()
        self.assertEqual(agent._latest_targeted_preflight_repair_status, "")


if __name__ == "__main__":
    unittest.main()
