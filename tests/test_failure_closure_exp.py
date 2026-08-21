from __future__ import annotations

import inspect
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml

from integrations.harbor.experimental.artifact_identity import artifact_identity
from integrations.harbor.experimental.develop_family_router import select_family
from integrations.harbor.experimental.failure_feedback_gate import (
    main as failure_feedback_main,
    prepare_retry_brief,
    validate_preflight_delta,
)
from integrations.harbor.experimental.transition_failure_feedback import (
    latest_transition_feedback,
    main as transition_failure_feedback_main,
)
from integrations.harbor.experimental.recovering_develop_guard import (
    close_cycle,
    open_cycle,
    open_review,
    route_review,
)
from integrations.harbor.experimental.artifact_identity import (
    artifact_progress_identity,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p31ExperimentalStatemCodex,
    EvidenceDevelopV4p32ExperimentalStatemCodex,
    EvidenceDevelopV4p33ExperimentalStatemCodex,
    EvidenceDevelopV4p34ExperimentalStatemCodex,
    EvidenceDevelopV4p35ExperimentalStatemCodex,
    EvidenceDevelopV4p36ExperimentalStatemCodex,
    EvidenceDevelopV4p38ExperimentalStatemCodex,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4p31-exp.yaml"
RUNBOOK_V4P32 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p32-exp.yaml"
RUNBOOK_V4P33 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p33-exp.yaml"
RUNBOOK_V4P34 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p34-exp.yaml"
RUNBOOK_V4P35 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p35-exp.yaml"
FAMILY_CATALOG = REPO / "examples/develop-family-router-v1.yaml"


class FailureClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "worker.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.ledger = self.root / "cycle-ledger.json"
        self.deadline = self.root / "deadline.json"
        self.run_id = "failure-closure-test"
        self.env = {
            "STATEM_RUN_ID": self.run_id,
            "STATEM_STATE_DIR": str(self.state_dir),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _state(self, node: str, entry_id: str) -> None:
        path = self.state_dir / "runs" / self.run_id / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "current": node,
                    "current_entry_id": entry_id,
                }
            ),
            encoding="utf-8",
        )

    def _seal(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "contract_seal",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-1",
            "baseline_artifact_identity": artifact_identity(self.app),
        }

    def _application(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "artifact_application_verification",
            "run_id": self.run_id,
            "node": "promote",
            "entry_id": "promote-1",
            "observed_artifact_identity": artifact_identity(self.app),
            "verified": True,
        }

    def _family(
        self,
        reserve: int = 2100,
        revision_reserve: int = 1500,
    ) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "develop_family_selection",
            "family_id": "structured-transformation",
            "retry_reserve_seconds": reserve,
            "revision_reserve_seconds": revision_reserve,
        }

    def _replay(self, *, owner: str = "lead_solver") -> dict[str, object]:
        evidence = "public replay exposed an encoded boundary mismatch"
        rationale = "append the exact encoded boundary to independent acceptance"
        return {
            "status": "recoverable_failure",
            "evidence": [evidence],
            "residual_risk": [],
            "next_gap": "repair the encoded boundary handling",
            "failure_ownership": {
                "failure_class": "implementation_defect",
                "owner_role": owner,
                "observed_failure": evidence,
                "causal_hypothesis": "the candidate normalizes before classifying the boundary",
                "repair_action": "repair the encoded boundary handling",
                "required_validation_update": rationale,
                "confidence": "high",
            },
            "validation_delta": {
                "action": "append_regression",
                "discriminating_check": "replay literal and encoded boundary pairs on the public consumer",
                "success_interpretation": "only the contract-defined dangerous form is rejected",
                "failure_interpretation": "the repair still conflates literal and encoded forms",
                "preserves_prior_obligations": True,
                "superseded_check_ids": [],
                "rationale": rationale,
            },
            "hard_gap_resolutions": [],
        }

    def _open(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(ledger_path=self.ledger, seal=self._seal(), max_cycles=2)

    def test_family_selection_is_deterministic_from_primary_profile(self) -> None:
        catalog = yaml.safe_load(FAMILY_CATALOG.read_text(encoding="utf-8"))
        profile = {
            "version": 1,
            "kind": "review_profile_selection",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-1",
            "primary": "parsing-transformation",
            "secondary": ["security-protocols", "stateful-systems"],
        }
        selected = select_family(catalog=catalog, review_profile=profile)
        self.assertEqual(selected["family_id"], "structured-transformation")
        self.assertEqual(selected["retry_reserve_seconds"], 2100)
        self.assertEqual(selected["revision_reserve_seconds"], 1500)

    def test_v4p32_runbook_requires_stratum_complete_replay(self) -> None:
        text = RUNBOOK_V4P32.read_text(encoding="utf-8")
        validate_spec(RUNBOOK_V4P32, strict=True)
        self.assertIn("frontier-bench-statem-evidence-develop-v4p32-experiment", text)
        self.assertIn("covered_strata", text)
        self.assertEqual(text.count("--require-strata-coverage"), 2)

        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p32ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p32-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P32)

    def test_v4p33_runbook_canonicalizes_mechanical_requirement_ids(self) -> None:
        text = RUNBOOK_V4P33.read_text(encoding="utf-8")
        validate_spec(RUNBOOK_V4P33, strict=True)
        self.assertIn("frontier-bench-statem-evidence-develop-v4p33-experiment", text)
        self.assertIn("collisions after canonicalization", text)
        self.assertEqual(text.count("--require-strata-coverage"), 2)

        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p33ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p33-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P33)

    def test_v4p34_runbook_gates_revision_on_remaining_deadline(self) -> None:
        text = RUNBOOK_V4P34.read_text(encoding="utf-8")
        validate_spec(RUNBOOK_V4P34, strict=True)
        self.assertIn("frontier-bench-statem-evidence-develop-v4p34-experiment", text)
        self.assertIn("--require-deadline-budget", text)
        self.assertIn("revision reserve", text)

        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p34ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p34-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P34)

    def test_v4p35_runbook_binds_candidate_blind_obligation_closure(self) -> None:
        text = RUNBOOK_V4P35.read_text(encoding="utf-8")
        validate_spec(RUNBOOK_V4P35, strict=True)
        self.assertIn("frontier-bench-statem-evidence-develop-v4p35-experiment", text)
        self.assertEqual(text.count("--preflight-evidence"), 6)

        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p35ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p35-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P35)

    def test_review_deadline_gate_quarantines_infeasible_revision(self) -> None:
        self._open()
        self._state("falsify", "falsify-1")
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "revise",
        }
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 300}),
            encoding="utf-8",
        )
        with patch.dict("os.environ", self.env, clear=False):
            open_review(ledger_path=self.ledger)
            route = route_review(
                ledger_path=self.ledger,
                promotion_decision=decision,
                require_deadline_budget=True,
                deadline_path=self.deadline,
                family_selection=self._family(revision_reserve=1500),
            )
        self.assertEqual(route["route"], "quarantine")
        self.assertFalse(route["revision_deadline_feasible"])
        self.assertTrue(route["deadline_budget_degraded"])
        self.assertEqual(
            route["revision_deadline_reason"],
            "insufficient_complete_revision_reserve",
        )

    def test_review_deadline_gate_allows_complete_revision(self) -> None:
        self._open()
        self._state("falsify", "falsify-1")
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "revise",
        }
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 1800}),
            encoding="utf-8",
        )
        with patch.dict("os.environ", self.env, clear=False):
            open_review(ledger_path=self.ledger)
            route = route_review(
                ledger_path=self.ledger,
                promotion_decision=decision,
                require_deadline_budget=True,
                deadline_path=self.deadline,
                family_selection=self._family(revision_reserve=1500),
            )
        self.assertEqual(route["route"], "revise")
        self.assertTrue(route["revision_deadline_feasible"])
        self.assertFalse(route["deadline_budget_degraded"])
        self.assertEqual(
            route["revision_deadline_reason"],
            "complete_revision_reserve_available",
        )

    def test_deadline_gate_requires_a_complete_family_cycle_reserve(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 1200}),
            encoding="utf-8",
        )
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=self._replay(),
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "handoff")
        self.assertTrue(decision["information_gain_authorized"])
        self.assertTrue(decision["failure_owner_authorized"])
        self.assertFalse(decision["deadline_feasible"])
        self.assertEqual(decision["deadline_reason"], "insufficient_full_cycle_reserve")

    def test_deadline_gate_allows_a_complete_family_cycle(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 3600}),
            encoding="utf-8",
        )
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=self._replay(),
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "retry")
        self.assertTrue(decision["information_gain_authorized"])
        self.assertTrue(decision["failure_owner_authorized"])
        self.assertTrue(decision["deadline_feasible"])
        self.assertEqual(decision["deadline_reason"], "full_cycle_reserve_available")

    def test_adapter_owned_failure_hands_off_without_consuming_a_cycle(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 3600}),
            encoding="utf-8",
        )
        replay = self._replay()
        rationale = "repair the evidence projector before another task-agent cycle"
        replay["failure_ownership"] = {
            "failure_class": "evidence_projection_gap",
            "owner_role": "adapter",
            "observed_failure": replay["evidence"][0],
            "causal_hypothesis": "the projector omitted a public artifact field",
            "repair_action": replay["next_gap"],
            "required_validation_update": rationale,
            "confidence": "high",
        }
        replay["validation_delta"] = {
            "action": "no_public_delta",
            "discriminating_check": "re-export the same public evidence after projector repair",
            "success_interpretation": "the existing evidence is represented completely",
            "failure_interpretation": "the projector remains incomplete",
            "preserves_prior_obligations": True,
            "superseded_check_ids": [],
            "rationale": rationale,
        }
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=replay,
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "handoff")
        self.assertFalse(decision["information_gain_authorized"])
        self.assertFalse(decision["failure_owner_authorized"])
        self.assertTrue(decision["deadline_feasible"])

    def test_failure_owner_mapping_is_host_validated(self) -> None:
        self._open()
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "must be owned by 'lead_solver'"):
                close_cycle(
                    ledger_path=self.ledger,
                    replay_draft=self._replay(owner="test_planner"),
                    application=self._application(),
                    artifact_root=self.app,
                    require_information_gain=True,
                    require_failure_closure=True,
                    deadline_path=self.deadline,
                    family_selection=self._family(),
                )

    def test_validation_delta_is_carried_into_next_candidate_blind_plan(self) -> None:
        replay = self._replay()
        decision = {
            "version": 1,
            "kind": "recovering_develop_replay_decision",
            "action": "retry",
            "failure_ownership": replay["failure_ownership"],
            "validation_delta": replay["validation_delta"],
        }
        brief = prepare_retry_brief(decision)
        check = replay["validation_delta"]["discriminating_check"]
        preflight = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "encoded_boundary_regression",
                        "required_strata": [check],
                    }
                ]
            },
        }
        receipt = validate_preflight_delta(
            brief=brief,
            preflight_evidence=preflight,
        )
        self.assertTrue(receipt["applied"])
        self.assertEqual(
            receipt["matched_requirement_ids"], ["encoded_boundary_regression"]
        )

        preflight["acceptance_plan"]["requirements"][0]["required_strata"] = [
            "an unrelated check"
        ]
        with self.assertRaisesRegex(ValueError, "did not append the exact"):
            validate_preflight_delta(brief=brief, preflight_evidence=preflight)

    def test_failed_validation_removes_stale_success_receipt(self) -> None:
        replay = self._replay()
        brief = prepare_retry_brief(
            {
                "version": 1,
                "kind": "recovering_develop_replay_decision",
                "action": "retry",
                "failure_ownership": replay["failure_ownership"],
                "validation_delta": replay["validation_delta"],
            }
        )
        preflight = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "acceptance_plan": {"requirements": []},
        }
        brief_path = self.root / "retry-brief.json"
        preflight_path = self.root / "preflight-evidence.json"
        output_path = self.root / "validation-delta-receipt.json"
        brief_path.write_text(json.dumps(brief), encoding="utf-8")
        preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "kind": "validation_delta_application",
                    "required": False,
                    "applied": True,
                }
            ),
            encoding="utf-8",
        )

        with patch("builtins.print"):
            exit_code = failure_feedback_main(
                [
                    "validate-preflight",
                    "--brief",
                    str(brief_path),
                    "--preflight-evidence",
                    str(preflight_path),
                    "--output",
                    str(output_path),
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertFalse(output_path.exists())

    def test_v4p40_blocker_becomes_bounded_resume_feedback(self) -> None:
        state = {
            "current": "solve",
            "current_entry_id": "20260821T023710Z-cdc93414",
            "history": [
                {
                    "event": "goto_blocked",
                    "from": "solve",
                    "to": "falsify",
                    "stage": "before_transfer",
                    "current_entry_id": "20260821T023710Z-cdc93414",
                    "results": [
                        {
                            "type": "command",
                            "purpose": "before_transfer",
                            "passed": False,
                            "blocking": True,
                            "exit_code": 1,
                            "on_failure": "block",
                            "output": (
                                "failure feedback gate: candidate-blind acceptance "
                                "plan did not append the exact prior validation delta\n"
                                + "raw details must not enter the receipt"
                            ),
                        }
                    ],
                }
            ],
        }
        receipt = latest_transition_feedback(state)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["current_state"], "solve")
        self.assertEqual(receipt["target_state"], "falsify")
        self.assertEqual(
            receipt["failed_checks"][0]["summary"],
            "failure feedback gate: candidate-blind acceptance plan did not "
            "append the exact prior validation delta",
        )
        self.assertEqual(len(receipt["blocker_fingerprint"]), 64)
        self.assertNotIn("raw details", json.dumps(receipt))

    def test_transition_feedback_redacts_ids_and_caps_failed_checks(self) -> None:
        results = [
            {
                "type": "command",
                "purpose": f"gate-{index}",
                "passed": False,
                "blocking": True,
                "exit_code": 1,
                "on_failure": "block",
                "output": (
                    "blocked receipt "
                    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef "
                    "123e4567-e89b-12d3-a456-426614174000"
                ),
            }
            for index in range(6)
        ]
        receipt = latest_transition_feedback(
            {
                "current": "solve",
                "current_entry_id": "entry-1",
                "history": [
                    {
                        "event": "goto_blocked",
                        "from": "solve",
                        "to": "falsify",
                        "stage": "before_transfer",
                        "current_entry_id": "entry-1",
                        "results": results,
                    }
                ],
            }
        )
        assert receipt is not None
        self.assertEqual(len(receipt["failed_checks"]), 4)
        self.assertIn("<sha256>", receipt["failed_checks"][0]["summary"])
        self.assertIn("<uuid>", receipt["failed_checks"][0]["summary"])

    def test_transition_feedback_assigns_plan_owner_and_counts_repeats(self) -> None:
        blocked = {
            "event": "goto_blocked",
            "from": "solve",
            "to": "falsify",
            "stage": "before_transfer",
            "current_entry_id": "entry-1",
            "results": [
                {
                    "type": "command",
                    "purpose": "before_transfer",
                    "passed": False,
                    "blocking": True,
                    "exit_code": 1,
                    "on_failure": "block",
                    "output": (
                        "failure feedback gate: candidate-blind acceptance plan "
                        "did not append the exact prior validation delta"
                    ),
                }
            ],
        }
        receipt = latest_transition_feedback(
            {
                "current": "solve",
                "current_entry_id": "entry-1",
                "history": [blocked, blocked, blocked],
            }
        )
        assert receipt is not None
        failed = receipt["failed_checks"][0]
        self.assertEqual(failed["failure_class"], "acceptance_plan_gap")
        self.assertEqual(failed["repair_owner"], "test_planner")
        self.assertIn("retry-brief.json", failed["repair_action"])
        self.assertEqual(receipt["repeat_count"], 3)
        self.assertTrue(receipt["repair_budget_exhausted"])

    def test_no_blocker_removes_stale_transition_feedback(self) -> None:
        state_path = self.root / "state.json"
        output_path = self.root / "transition-feedback.json"
        state_path.write_text(
            json.dumps(
                {
                    "current": "solve",
                    "current_entry_id": "entry-1",
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        output_path.write_text("stale", encoding="utf-8")
        with patch("builtins.print"):
            exit_code = transition_failure_feedback_main(
                [
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertFalse(output_path.exists())

    def test_v4p31_adapter_and_runbook_are_versioned_and_valid(self) -> None:
        agent = EvidenceDevelopV4p31ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p31ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("develop_family_router.py", names)
        self.assertIn("develop-family-router-v1.yaml", names)
        self.assertIn("failure_feedback_gate.py", names)
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p31-exp",
        )
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600
        instruction = agent._augment_instruction("task", "run", "context")
        self.assertIn("family/family-selection.json", instruction)
        self.assertIn("recovering-develop/retry-brief.json", instruction)
        validate_spec(RUNBOOK, strict=True)


class V4p32ProgressWitnessTest(unittest.IsolatedAsyncioTestCase):
    async def test_progress_identity_uses_metadata_and_excludes_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "artifact.txt"
            artifact.write_text("before", encoding="utf-8")
            before = artifact_progress_identity(root)
            artifact.write_text("after-change", encoding="utf-8")
            self.assertNotEqual(artifact_progress_identity(root), before)

            stable = artifact_progress_identity(root)
            (root / "progress.md").write_text("working", encoding="utf-8")
            excluded = root / "node_modules"
            excluded.mkdir()
            (excluded / "vendor.js").write_text("large-vendor-tree", encoding="utf-8")
            self.assertEqual(artifact_progress_identity(root), stable)

    async def test_same_state_artifact_or_receipt_progress_changes_identity(self) -> None:
        agent = object.__new__(EvidenceDevelopV4p32ExperimentalStatemCodex)
        agent._statem_env = lambda run_id: {"STATEM_RUN_ID": run_id}
        agent.exec_as_agent = AsyncMock(
            side_effect=[
                SimpleNamespace(stdout="witness-a\n"),
                SimpleNamespace(stdout="witness-b\n"),
                SimpleNamespace(stdout="witness-b\n"),
            ]
        )
        current = {"current": "solve", "current_entry_id": "solve-1"}

        first = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )
        second = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )
        unchanged = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )

        self.assertEqual(first[:2], ("solve", "solve-1"))
        self.assertNotEqual(first, second)
        self.assertEqual(second, unchanged)
        command = agent.exec_as_agent.await_args_list[0].kwargs["command"]
        self.assertIn("artifact_progress_identity", command)
        self.assertIn("/app", command)
        self.assertIn("cycle-ledger.json", command)


class V4p36LifecycleProgressTest(unittest.TestCase):
    def test_candidate_blind_drafts_are_progress_witnesses(self) -> None:
        paths = EvidenceDevelopV4p36ExperimentalStatemCodex._PROGRESS_RECEIPTS

        self.assertIn("multirole/solver-plan-draft.json", paths)
        self.assertIn("multirole/review-profile-draft.json", paths)
        self.assertIn("multirole/acceptance-evidence-draft.json", paths)

    def test_lifecycle_budget_allows_bounded_plan_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p36ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )

        self.assertEqual(agent._session_no_progress_limit(), 4)
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p36-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK_V4P35)


class V4p38BlockerProgressTest(unittest.IsolatedAsyncioTestCase):
    def test_blocker_scan_starts_at_first_current_entry_event(self) -> None:
        source = inspect.getsource(
            EvidenceDevelopV4p38ExperimentalStatemCodex._session_progress_identity
        )

        self.assertIn(
            '"    if start < 0 and str(event.get(\'entry_id\') or \'\') == entry_id',
            source,
        )

    async def test_same_blocker_dominates_changed_artifact_witness(self) -> None:
        agent = object.__new__(EvidenceDevelopV4p38ExperimentalStatemCodex)
        agent._statem_env = lambda run_id: {"STATEM_RUN_ID": run_id}
        agent.exec_as_agent = AsyncMock(
            side_effect=[
                SimpleNamespace(stdout="artifact-a\n"),
                SimpleNamespace(stdout="blocked:same\n"),
                SimpleNamespace(stdout="artifact-b\n"),
                SimpleNamespace(stdout="blocked:same\n"),
            ]
        )
        current = {"current": "solve", "current_entry_id": "solve-1"}

        first = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )
        second = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )

        self.assertEqual(first, ("solve", "solve-1", "blocked:same"))
        self.assertEqual(second, first)

    async def test_changed_blocker_resets_progress_identity(self) -> None:
        agent = object.__new__(EvidenceDevelopV4p38ExperimentalStatemCodex)
        agent._statem_env = lambda run_id: {"STATEM_RUN_ID": run_id}
        agent.exec_as_agent = AsyncMock(
            side_effect=[
                SimpleNamespace(stdout="artifact-a\n"),
                SimpleNamespace(stdout="blocked:first\n"),
                SimpleNamespace(stdout="artifact-b\n"),
                SimpleNamespace(stdout="blocked:second\n"),
            ]
        )
        current = {"current": "solve", "current_entry_id": "solve-1"}

        first = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )
        second = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )

        self.assertNotEqual(first, second)

    async def test_no_blocker_preserves_artifact_progress_identity(self) -> None:
        agent = object.__new__(EvidenceDevelopV4p38ExperimentalStatemCodex)
        agent._statem_env = lambda run_id: {"STATEM_RUN_ID": run_id}
        agent.exec_as_agent = AsyncMock(
            side_effect=[
                SimpleNamespace(stdout="artifact-a\n"),
                SimpleNamespace(stdout="\n"),
                SimpleNamespace(stdout="artifact-b\n"),
                SimpleNamespace(stdout="\n"),
            ]
        )
        current = {"current": "solve", "current_entry_id": "solve-1"}

        first = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )
        second = await agent._session_progress_identity(
            SimpleNamespace(), "run-1", current
        )

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
