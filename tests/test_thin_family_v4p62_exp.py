from __future__ import annotations

import json
import unittest
from pathlib import Path

from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    ThinFamilyV4p62ExperimentalStatemCodex,
    select_thin_family_practice,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v1.json"
RUNBOOK = REPO / "examples" / "terminal-bench-agent-thin-v4p62-exp.yaml"


class ThinFamilyV4p62Test(unittest.TestCase):
    def test_thin_runbook_is_strict_and_small(self) -> None:
        receipt = validate_spec(str(RUNBOOK), strict=True)
        self.assertTrue(receipt["ok"])
        self.assertLessEqual(len(RUNBOOK.read_text(encoding="utf-8").splitlines()), 100)
        self.assertEqual(receipt["initial"], "solve")

    def test_ordinary_task_keeps_empty_family_route(self) -> None:
        receipt = select_thin_family_practice(
            "Implement a CLI that prints the requested JSON fields.",
            CATALOG,
            activation_mode="active",
        )
        self.assertFalse(receipt["selected"])
        self.assertFalse(receipt["activated"])
        self.assertNotIn("compact", receipt)

    def test_one_weak_keyword_does_not_activate_a_family(self) -> None:
        receipt = select_thin_family_practice(
            "Improve server output formatting.",
            CATALOG,
            activation_mode="active",
        )
        self.assertFalse(receipt["selected"])

    def test_stateful_route_requires_two_public_signal_groups(self) -> None:
        receipt = select_thin_family_practice(
            "Repair MVCC compaction so transaction visibility remains consistent after replay.",
            CATALOG,
            activation_mode="active",
        )
        self.assertTrue(receipt["selected"])
        self.assertFalse(receipt["activated"])
        self.assertEqual(receipt["activation_reason"], "unadmitted_shadow")
        self.assertEqual(receipt["family"], "stateful-lifecycle")
        self.assertEqual(receipt["practice_id"], "stateful_lifecycle_compact")
        self.assertEqual(len(receipt["trigger_evidence"]), 2)
        self.assertFalse(receipt["admitted"])

    def test_priority_selects_at_most_one_family(self) -> None:
        receipt = select_thin_family_practice(
            "Optimize streaming service throughput while preserving replay consistency and cache scaling.",
            CATALOG,
            activation_mode="active",
        )
        self.assertGreaterEqual(receipt["eligible_match_count"], 1)
        self.assertEqual(receipt["family"], "stateful-lifecycle")
        self.assertFalse(receipt["activated"])

    def test_shadow_records_selection_without_solver_injection(self) -> None:
        instruction = (
            "Optimize graph search performance and scaling while preserving exact results."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="shadow",
        )
        self.assertTrue(selection["selected"])
        self.assertFalse(selection["activated"])

        agent = ThinFamilyV4p62ExperimentalStatemCodex.__new__(
            ThinFamilyV4p62ExperimentalStatemCodex
        )
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "shadow"
        agent._thin_family_selection = selection
        text = agent._augment_instruction(
            instruction,
            "run-1",
            "Run: run-1\nCurrent: solve\nNext: verify",
        )
        self.assertNotIn("Conditionally selected compact family practice", text)
        self.assertNotIn("acceptance_population_and_margin", text)

    def test_active_projection_contains_compact_but_not_detailed_practice(self) -> None:
        instruction = (
            "Optimize graph search performance and scaling while preserving exact results."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="active",
        )
        agent = ThinFamilyV4p62ExperimentalStatemCodex.__new__(
            ThinFamilyV4p62ExperimentalStatemCodex
        )
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "active"
        agent._thin_family_selection = selection
        text = agent._augment_instruction(
            instruction,
            "run-1",
            "Run: run-1\nCurrent: solve\nNext: verify",
        )
        self.assertIn("Conditionally selected compact family practice", text)
        self.assertIn("algorithm-performance", text)
        self.assertIn("fixed representative population", text)
        self.assertNotIn("paired_measurement_validity", text)
        self.assertNotIn("acceptance_population_and_margin", text)

    def test_catalog_keeps_detailed_practices_reviewer_only_and_unadmitted(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(catalog["selection_policy"]["max_selected"], 1)
        self.assertFalse(catalog["selection_policy"]["task_name_routing"])
        admitted = []
        for practice in catalog["practices"]:
            self.assertTrue(practice["detailed"]["reviewer_only"])
            if practice["validation"]["admitted"]:
                admitted.append(practice["practice_id"])
            self.assertGreaterEqual(len(practice["compact"]["obligations"]), 2)
            self.assertGreaterEqual(len(practice["detailed"]["prioritized_checks"]), 3)
        self.assertEqual(admitted, ["algorithm_performance_compact"])

    def test_invalid_activation_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_thin_family_practice(
                "Do the task.",
                CATALOG,
                activation_mode="blocking",
            )


if __name__ == "__main__":
    unittest.main()
