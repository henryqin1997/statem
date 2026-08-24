from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p74_exp import (
    ThinFamilyV4p74ExperimentalStatemCodex,
    build_thin_reviewer_projection,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v2.json"


class ThinFamilyV4p74Test(unittest.TestCase):
    def _agent(self, supplements=()):
        agent = ThinFamilyV4p74ExperimentalStatemCodex.__new__(
            ThinFamilyV4p74ExperimentalStatemCodex
        )
        agent._development_practice_id = "structured_transformation_compact"
        agent._development_supplement_ids = tuple(supplements)
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "active"
        agent._thin_family_selection = None
        agent._direct_bypass_active = False
        agent.logs_dir = Path(tempfile.gettempdir()) / "v4p74-test-logs"
        return agent

    def test_adapted_cell_activates_only_explicit_supplement_set(self) -> None:
        instruction = (
            "Transform and preserve underlying entities across aliases and "
            "effective-dated history with --seed; seeded fake date and gaussian "
            "transforms change."
        )
        agent = self._agent(["seeded_transform_sensitivity_compact"])
        with patch.object(StatemCodex, "run", new=AsyncMock()) as statem_run:
            asyncio.run(
                agent.run(
                    instruction,
                    SimpleNamespace(default_user=1000),
                    SimpleNamespace(metadata={}),
                )
            )
        statem_run.assert_awaited_once()
        active = [
            item["supplement_id"]
            for item in agent._thin_family_selection["supplements"]
            if item["activated"]
        ]
        self.assertEqual(active, ["seeded_transform_sensitivity_compact"])

    def test_solver_gets_compact_and_invoked_reviewer_gets_detail(self) -> None:
        instruction = (
            "Improve graph search performance and cache scaling while preserving "
            "exact semantics."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="active",
        )
        agent = self._agent()
        agent._thin_family_selection = selection
        solver_text = agent._augment_instruction(
            instruction,
            "run-1",
            "Run: run-1\nCurrent: solve\nNext: verify",
        )
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertIn("fixed representative population", solver_text)
        self.assertNotIn("paired_measurement_validity", solver_text)
        self.assertIn(
            "paired_measurement_validity",
            reviewer["detailed"]["prioritized_checks"],
        )

    def test_unactivated_practice_cannot_load_detail(self) -> None:
        selection = select_thin_family_practice(
            "Parse nested encoded input while preserving ordering.",
            CATALOG,
            activation_mode="active",
        )
        self.assertFalse(selection["activated"])
        with self.assertRaisesRegex(ValueError, "activated practice"):
            build_thin_reviewer_projection(selection, CATALOG)

    def test_unknown_adapted_supplement_fails_closed(self) -> None:
        instruction = "Transform nested encoded input while preserving ordering."
        agent = self._agent(["missing_supplement"])
        with patch.object(StatemCodex, "run", new=AsyncMock()) as statem_run:
            with self.assertRaisesRegex(RuntimeError, "supplement mismatch"):
                asyncio.run(
                    agent.run(
                        instruction,
                        SimpleNamespace(default_user=1000),
                        SimpleNamespace(metadata={}),
                    )
                )
        statem_run.assert_not_awaited()

    def test_agent_identity_is_distinct(self) -> None:
        self.assertEqual(
            ThinFamilyV4p74ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p74-exp",
        )


if __name__ == "__main__":
    unittest.main()
