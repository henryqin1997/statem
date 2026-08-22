from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from integrations.harbor.experimental.artifact_identity import (
    artifact_identity,
    stable_sha256,
)
from integrations.harbor.experimental.filesystem_artifact_provider import (
    apply_snapshot,
    snapshot_artifact,
)
from integrations.harbor.experimental.submission_eligibility_gate import (
    decide_submission,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p56ExperimentalStatemCodex,
    EvidenceDevelopV4p57ExperimentalStatemCodex,
    EvidenceDevelopV4p59ExperimentalStatemCodex,
    EvidenceDevelopV4p60ExperimentalStatemCodex,
    EvidenceDevelopV4p61ExperimentalStatemCodex,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4p56-exp.yaml"
RUNBOOK_V59 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p59-exp.yaml"
RUNBOOK_V60 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p60-exp.yaml"
RUNBOOK_V61 = REPO / "examples/frontier-bench-agent-evidence-develop-v4p61-exp.yaml"


class SubmissionLifecycleV4p56Test(unittest.TestCase):
    def test_v4p61_runbook_requires_scope_exclusion_audit(self) -> None:
        self.assertTrue(validate_spec(str(RUNBOOK_V61), strict=True)["ok"])
        spec = yaml.safe_load(RUNBOOK_V61.read_text(encoding="utf-8"))
        self.assertEqual(
            spec["name"],
            "frontier-bench-statem-evidence-develop-v4p61-experiment",
        )
        solve_hooks = spec["nodes"]["solve"]["before_transfer"]
        require_preflight = next(
            hook["run"]
            for hook in solve_hooks
            if "require-preflight" in hook.get("run", "")
        )
        self.assertIn("--require-claim-boundary-closure", require_preflight)
        self.assertIn("--require-scope-exclusion-schema", require_preflight)

    def test_v4p61_adapter_binds_distinct_identity_and_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p61ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p61-exp",
        )
        self.assertEqual(Path(agent._runbook_path), RUNBOOK_V61)

    def test_v4p60_runbook_requires_claim_boundary_closure(self) -> None:
        self.assertTrue(validate_spec(str(RUNBOOK_V60), strict=True)["ok"])
        spec = yaml.safe_load(RUNBOOK_V60.read_text(encoding="utf-8"))
        self.assertEqual(
            spec["name"],
            "frontier-bench-statem-evidence-develop-v4p60-experiment",
        )
        solve_hooks = spec["nodes"]["solve"]["before_transfer"]
        require_preflight = next(
            hook["run"]
            for hook in solve_hooks
            if "require-preflight" in hook.get("run", "")
        )
        self.assertIn("--require-generalization-evidence-scope", require_preflight)
        self.assertIn("--require-claim-boundary-closure", require_preflight)

    def test_v4p60_adapter_binds_distinct_identity_and_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p60ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p60-exp",
        )
        self.assertEqual(Path(agent._runbook_path), RUNBOOK_V60)

    def test_v4p59_runbook_requires_generalization_evidence_scope(self) -> None:
        self.assertTrue(validate_spec(str(RUNBOOK_V59), strict=True)["ok"])
        spec = yaml.safe_load(RUNBOOK_V59.read_text(encoding="utf-8"))
        self.assertEqual(
            spec["name"],
            "frontier-bench-statem-evidence-develop-v4p59-experiment",
        )
        solve_hooks = spec["nodes"]["solve"]["before_transfer"]
        self.assertTrue(
            any(
                "--require-generalization-evidence-scope" in hook.get("run", "")
                for hook in solve_hooks
            )
        )
        result_schema = spec["nodes"]["falsify"]["multi_agent"][
            "result_schema"
        ]
        self.assertIn(
            "acceptance_obligation_assessments",
            result_schema["required"],
        )

    def test_v4p59_adapter_binds_distinct_identity_and_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p59ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p59-exp",
        )
        self.assertEqual(Path(agent._runbook_path), RUNBOOK_V59)

    def test_runbook_is_strictly_valid_and_routes_submission_explicitly(self) -> None:
        self.assertTrue(validate_spec(str(RUNBOOK), strict=True)["ok"])
        spec = yaml.safe_load(RUNBOOK.read_text(encoding="utf-8"))
        self.assertEqual(
            spec["name"],
            "frontier-bench-statem-evidence-develop-v4p56-experiment",
        )
        self.assertIn("submission_gate", spec["nodes"])
        self.assertIn("submission_restore", spec["nodes"])
        edges = {(edge["from"], edge["to"]): edge for edge in spec["edges"]}
        self.assertNotIn(("final_replay", "handoff"), edges)
        self.assertIn(("final_replay", "submission_gate"), edges)
        self.assertIn(("submission_gate", "handoff"), edges)
        self.assertIn(("submission_gate", "submission_restore"), edges)
        self.assertIn(("submission_restore", "handoff"), edges)
        self.assertIn(
            "--require-fallback",
            edges[("submission_gate", "submission_restore")]["condition"]["run"],
        )
        handoff_hooks = spec["nodes"]["handoff"]["in_hook"]
        self.assertTrue(
            any("--require-handoff" in hook["run"] for hook in handoff_hooks)
        )

    def test_adapter_binds_gate_identity_policy_and_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p56ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p56-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(
            agent._statem_env("run-1")["STATEM_SUBMISSION_POLICY"],
            "deadline_best_validated",
        )
        self.assertIn(
            "submission_eligibility_gate.py",
            [path.name for path in agent._verification_check_paths()],
        )
        self.assertIn(
            "submission/submission-eligibility.json",
            agent._PROGRESS_RECEIPTS,
        )
        instruction = agent._augment_instruction("task", "run-1", "solve")
        self.assertIn("submission eligibility are separate host decisions", instruction)
        self.assertIn("only advisory uncertainty", instruction)

    def test_v4p57_changes_identity_but_reuses_submission_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4p57ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p57-exp",
        )
        self.assertEqual(agent._runbook_path, RUNBOOK)
        self.assertEqual(
            agent._PROGRESS_RECEIPTS,
            EvidenceDevelopV4p56ExperimentalStatemCodex._PROGRESS_RECEIPTS,
        )

    def test_adapter_accepts_strict_policy_and_rejects_unknown_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            strict = EvidenceDevelopV4p56ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
                submission_policy="strict_review",
            )
            self.assertEqual(
                strict._statem_env("run-1")["STATEM_SUBMISSION_POLICY"],
                "strict_review",
            )
            with self.assertRaisesRegex(ValueError, "unsupported submission policy"):
                EvidenceDevelopV4p56ExperimentalStatemCodex(
                    logs_dir=Path(temp_dir),
                    model_name="gpt-5.6-sol",
                    submission_policy="unknown",
                )

    def test_negative_evidence_restores_exact_baseline_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = root / "app"
            app.mkdir()
            target = app / "worker.py"
            target.write_text("def work():\n    return 1\n", encoding="utf-8")
            baseline_identity = artifact_identity(app)
            env = {
                "STATEM_RUN_ID": "submission-restore",
                "STATEM_STATE_DIR": str(root / "state"),
                "STATEM_CURRENT": "submission_restore",
                "STATEM_ENTRY_ID": "entry-1",
            }
            with patch.dict("os.environ", env, clear=False):
                baseline = snapshot_artifact(
                    artifact_root=app,
                    provider_root=root / "provider",
                    kind="baseline",
                )
                target.write_text("def work():\n    return 2\n", encoding="utf-8")
                candidate = snapshot_artifact(
                    artifact_root=app,
                    provider_root=root / "provider",
                    kind="candidate",
                )
                quarantined = apply_snapshot(
                    artifact_root=app,
                    snapshot=candidate,
                    mode="quarantine",
                )

            promotion = {
                "version": 1,
                "kind": "promotion_authorization",
                "run_id": "submission-restore",
                "decision": "revise",
                "falsifier_verdict": "inconclusive",
                "candidate_artifact_identity": candidate["artifact_identity"],
                "baseline_artifact_identity": baseline["artifact_identity"],
                "checks": {"same_run": True, "candidate_bound": True},
                "blocking_contract_violations": [{"severity": "blocking"}],
                "blocking_regressions": [],
                "hard_contract_gaps": [],
                "acceptance_obligation_assessments": [
                    {"requirement_id": "public-check", "status": "falsified"}
                ],
            }
            route = {
                "version": 1,
                "kind": "recovering_develop_review_route",
                "run_id": "submission-restore",
                "promotion_decision": "revise",
                "promotion_decision_sha256": stable_sha256(promotion),
                "route": "quarantine",
                "repairable_rejection": True,
                "review_budget_exhausted": True,
                "deadline_budget_degraded": False,
            }
            acceptance = {
                "version": 1,
                "kind": "candidate_acceptance_replay",
                "run_id": "submission-restore",
                "candidate_artifact_identity": candidate["artifact_identity"],
                "execution_complete": True,
                "all_passed": False,
                "overall_status": "failed",
            }
            replay = {
                "version": 1,
                "kind": "recovering_develop_replay_decision",
                "run_id": "submission-restore",
                "status": "terminal_failure",
                "reported_status": "terminal_failure",
                "action": "handoff",
            }
            pending = decide_submission(
                promotion_decision=promotion,
                review_route=route,
                acceptance_replay=acceptance,
                replay_decision=replay,
                provider_application=quarantined,
            )
            self.assertEqual(pending["selected_submission_target"], "baseline")
            self.assertTrue(pending["fallback_required"])
            self.assertFalse(pending["handoff_eligible"])

            with patch.dict("os.environ", env, clear=False):
                restored = apply_snapshot(
                    artifact_root=app,
                    snapshot=baseline,
                    mode="restore",
                )
            closed = decide_submission(
                promotion_decision=promotion,
                review_route=route,
                acceptance_replay=acceptance,
                replay_decision=replay,
                provider_application=restored,
            )
            self.assertEqual(artifact_identity(app), baseline_identity)
            self.assertFalse(closed["fallback_required"])
            self.assertTrue(closed["handoff_eligible"])


if __name__ == "__main__":
    unittest.main()
