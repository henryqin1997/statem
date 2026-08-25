from __future__ import annotations

import unittest
from pathlib import Path

from statem.miniyaml import loads as load_yaml


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples" / "tb3-hyper-agent-development-v1.yaml"


class Tb3HyperAgentRunbookTest(unittest.TestCase):
    def test_hyper_states_cover_three_lanes_and_adapted_extraction(self) -> None:
        runbook = load_yaml(RUNBOOK.read_text(encoding="utf-8"))
        nodes = runbook["nodes"]
        self.assertTrue(
            {
                "triage",
                "raw_observe",
                "develop",
                "extract_practice",
                "causal_validate",
                "score",
                "safety",
                "archive",
            }.issubset(nodes)
        )
        self.assertIn("expected decision-changing information", nodes["triage"]["prompt"])
        self.assertIn("adapted causal evidence", nodes["develop"]["prompt"])
        self.assertIn("Do not require cross-task transfer", nodes["causal_validate"]["prompt"])
        self.assertIn("narrowest supported scope", nodes["triage"]["prompt"])
        self.assertIn("Develop local controls independently", nodes["develop"]["prompt"])
        self.assertIn("hack risk", nodes["extract_practice"]["prompt"])
        self.assertIn("convergence synthesis", nodes["causal_validate"]["prompt"])
        self.assertIn("declaration fields", nodes["triage"]["prompt"])
        self.assertIn("runtime model", nodes["triage"]["prompt"])

    def test_hyper_policy_is_not_a_task_solution_runbook(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8").lower()
        for forbidden in (
            "hidden verifier",
            "expected answer",
            "benchmark solution",
            "task name routing",
        ):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("/app", text)
        self.assertNotIn("task.txt", text)


if __name__ == "__main__":
    unittest.main()
