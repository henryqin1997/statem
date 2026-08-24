from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p70_exp import (
    ThinFamilyV4p70ExperimentalStatemCodex,
)
from integrations.harbor.statem_codex_thin_family_v4p71_exp import (
    ThinFamilyV4p71ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v1.json"


class ThinFamilyV4p71Test(unittest.TestCase):
    def _agent(
        self,
        practice_id: str | None,
    ) -> ThinFamilyV4p71ExperimentalStatemCodex:
        agent = ThinFamilyV4p71ExperimentalStatemCodex.__new__(
            ThinFamilyV4p71ExperimentalStatemCodex
        )
        agent._development_practice_id = practice_id
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "active"
        agent._thin_family_selection = None
        agent._direct_bypass_active = False
        agent.logs_dir = Path(tempfile.gettempdir()) / "v4p71-test-logs"
        return agent

    def test_explicit_adapted_practice_uses_thin_graph(self) -> None:
        agent = self._agent("stateful_lifecycle_compact")
        context = SimpleNamespace(metadata={})
        environment = SimpleNamespace(default_user=1000)
        with patch.object(StatemCodex, "run", new=AsyncMock()) as statem_run:
            asyncio.run(
                agent.run(
                    "Repair database transaction recovery and consistency.",
                    environment,
                    context,
                )
            )

        statem_run.assert_awaited_once()
        self.assertTrue(agent._thin_family_selection["activated"])
        self.assertTrue(agent._thin_family_selection["development_override"])
        self.assertFalse(agent._thin_family_selection["admitted"])
        self.assertEqual(
            agent._thin_family_selection["activation_reason"],
            "explicit_adapted_development",
        )

    def test_explicit_adapted_practice_mismatch_fails_closed(self) -> None:
        agent = self._agent("stateful_lifecycle_compact")
        context = SimpleNamespace(metadata={})
        environment = SimpleNamespace(default_user=1000)
        with patch.object(StatemCodex, "run", new=AsyncMock()) as statem_run:
            with self.assertRaisesRegex(RuntimeError, "adapted practice mismatch"):
                asyncio.run(
                    agent.run(
                        "Classify seven independent records.",
                        environment,
                        context,
                    )
                )

        statem_run.assert_not_awaited()

    def test_without_override_preserves_v4p70_routing(self) -> None:
        agent = self._agent(None)
        context = SimpleNamespace(metadata={})
        environment = SimpleNamespace(default_user=1000)
        with patch.object(
            ThinFamilyV4p70ExperimentalStatemCodex,
            "run",
            new=AsyncMock(),
        ) as parent_run:
            asyncio.run(
                agent.run("Classify seven independent records.", environment, context)
            )

        parent_run.assert_awaited_once()

    def test_agent_identity_is_distinct(self) -> None:
        self.assertEqual(
            ThinFamilyV4p71ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p71-exp",
        )


if __name__ == "__main__":
    unittest.main()
