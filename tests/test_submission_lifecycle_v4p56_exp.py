from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p56ExperimentalStatemCodex,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4p56-exp.yaml"


class SubmissionLifecycleV4p56Test(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
