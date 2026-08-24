from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.codex import Codex

from integrations.harbor.statem_codex_thin_family_v4p69_exp import (
    ThinFamilyV4p69ExperimentalStatemCodex,
)
from integrations.harbor.statem_codex_thin_family_v4p70_exp import (
    ThinFamilyV4p70ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v1.json"


class ThinFamilyV4p70Test(unittest.TestCase):
    def _agent(self, logs_dir: Path) -> ThinFamilyV4p70ExperimentalStatemCodex:
        agent = ThinFamilyV4p70ExperimentalStatemCodex.__new__(
            ThinFamilyV4p70ExperimentalStatemCodex
        )
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "active"
        agent._thin_family_selection = None
        agent._direct_bypass_active = False
        agent._source_manifest = {
            "manifest_sha256": "manifest-sha",
            "file_count": 10,
        }
        agent.logs_dir = logs_dir
        return agent

    def test_no_match_uses_native_direct_without_statem_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = self._agent(Path(temp_dir) / "logs")
            environment = SimpleNamespace(default_user=1000)
            context = SimpleNamespace(metadata={})
            with (
                patch.object(Codex, "run", new=AsyncMock()) as codex_run,
                patch.object(
                    Codex, "populate_context_post_run", return_value=None
                ),
                patch(
                    "integrations.harbor.statem_codex_thin_family_v4p70_exp."
                    "sync_remote_codex_sessions_for_atif",
                    new=AsyncMock(return_value=False),
                ),
                patch.object(
                    agent, "_remove_codex_session_logs", new=AsyncMock()
                ) as cleanup,
            ):
                asyncio.run(agent.run("Classify seven public records.", environment, context))

            codex_run.assert_awaited_once()
            cleanup.assert_awaited_once()
            receipt = context.metadata["statem"]["thin_family_selection"]
            self.assertFalse(receipt["selected"])
            self.assertFalse(receipt["activated"])
            self.assertEqual(receipt["activation_reason"], "no_match")
            self.assertEqual(
                context.metadata["statem"]["execution_mode"],
                "native_direct_bypass",
            )

    def test_unadmitted_match_also_stays_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = self._agent(Path(temp_dir) / "logs")
            environment = SimpleNamespace(default_user=1000)
            context = SimpleNamespace(metadata={})
            with (
                patch.object(Codex, "run", new=AsyncMock()) as codex_run,
                patch.object(
                    Codex, "populate_context_post_run", return_value=None
                ),
                patch(
                    "integrations.harbor.statem_codex_thin_family_v4p70_exp."
                    "sync_remote_codex_sessions_for_atif",
                    new=AsyncMock(return_value=False),
                ),
                patch.object(
                    agent, "_remove_codex_session_logs", new=AsyncMock()
                ),
            ):
                asyncio.run(
                    agent.run(
                        "Parse nested input while preserving encoded fields.",
                        environment,
                        context,
                    )
                )

            codex_run.assert_awaited_once()
            receipt = context.metadata["statem"]["thin_family_selection"]
            self.assertTrue(receipt["selected"])
            self.assertFalse(receipt["activated"])
            self.assertEqual(receipt["activation_reason"], "unadmitted_shadow")

    def test_admitted_match_uses_thin_statem_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = self._agent(Path(temp_dir) / "logs")
            environment = SimpleNamespace(default_user=1000)
            context = SimpleNamespace(metadata={})
            with patch.object(
                ThinFamilyV4p69ExperimentalStatemCodex,
                "run",
                new=AsyncMock(),
            ) as statem_run:
                asyncio.run(
                    agent.run(
                        "Improve graph search performance and scaling with exact semantics.",
                        environment,
                        context,
                    )
                )

            statem_run.assert_awaited_once()
            self.assertTrue(agent._thin_family_selection["activated"])

    def test_direct_flags_do_not_enable_statem_hook_trust_bypass(self) -> None:
        agent = ThinFamilyV4p70ExperimentalStatemCodex.__new__(
            ThinFamilyV4p70ExperimentalStatemCodex
        )
        agent._direct_bypass_active = True
        agent._extra_env = {}
        with patch.object(Codex, "build_cli_flags", return_value=""):
            flags = agent.build_cli_flags()
        self.assertNotIn("hook-trust", flags)

    def test_agent_identity_is_distinct(self) -> None:
        self.assertEqual(
            ThinFamilyV4p70ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p70-exp",
        )


if __name__ == "__main__":
    unittest.main()
