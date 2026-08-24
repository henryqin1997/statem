from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p69_exp import (
    ThinFamilyV4p69ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v1.json"
RUNBOOK = REPO / "examples" / "terminal-bench-agent-thin-v4p62-exp.yaml"


class ThinFamilyV4p69Test(unittest.TestCase):
    def test_unadmitted_match_is_shadow_only(self) -> None:
        receipt = select_thin_family_practice(
            "Parse nested input while preserving encoded fields.",
            CATALOG,
            activation_mode="active",
        )
        self.assertTrue(receipt["selected"])
        self.assertFalse(receipt["activated"])
        self.assertEqual(receipt["activation_reason"], "unadmitted_shadow")

    def test_admitted_algorithm_practice_activates(self) -> None:
        receipt = select_thin_family_practice(
            "Improve graph search performance and scaling with exact semantics.",
            CATALOG,
            activation_mode="active",
        )
        self.assertTrue(receipt["selected"])
        self.assertTrue(receipt["activated"])
        self.assertEqual(receipt["practice_id"], "algorithm_performance_compact")
        self.assertEqual(receipt["activation_reason"], "admitted_active")

    def test_manifest_identity_ignores_worktree_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifests = []
            for name in ("checkout-a", "checkout-b"):
                root = Path(temp_dir) / name
                shutil.copytree(REPO / "statem", root / "statem")
                (root / "examples").mkdir(parents=True)
                shutil.copy2(RUNBOOK, root / "examples" / RUNBOOK.name)
                shutil.copy2(CATALOG, root / "examples" / CATALOG.name)

                agent = ThinFamilyV4p69ExperimentalStatemCodex.__new__(
                    ThinFamilyV4p69ExperimentalStatemCodex
                )
                agent._statem_source_dir = root
                agent._runbook_path = root / "examples" / RUNBOOK.name
                agent._practice_catalog_path = root / "examples" / CATALOG.name
                manifests.append(agent._build_source_manifest())

        self.assertEqual(manifests[0]["source_root"], "statem")
        self.assertEqual(
            manifests[0]["manifest_sha256"], manifests[1]["manifest_sha256"]
        )
        self.assertEqual(
            agent._public_source_manifest(manifests[0]),
            agent._public_source_manifest(manifests[1]),
        )

    def test_agent_identity_is_distinct(self) -> None:
        self.assertEqual(
            ThinFamilyV4p69ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p69-exp",
        )


if __name__ == "__main__":
    unittest.main()
