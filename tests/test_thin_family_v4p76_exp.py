from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from statem.core import StatemSpec

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p76_exp import (
    ThinFamilyV4p76ExperimentalStatemCodex,
    build_phased_runbook_overlay,
    build_solver_projection,
    build_thin_reviewer_projection,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v4.json"
RUNBOOK = REPO / "examples" / "terminal-bench-agent-thin-v4p62-exp.yaml"


class ThinFamilyV4p76Test(unittest.TestCase):
    def _agent(self, supplements=(), practice_id="structured_transformation_compact"):
        agent = ThinFamilyV4p76ExperimentalStatemCodex.__new__(
            ThinFamilyV4p76ExperimentalStatemCodex
        )
        agent._development_practice_id = practice_id
        agent._development_supplement_ids = tuple(supplements)
        agent._practice_catalog_path = CATALOG
        agent._activation_mode = "active"
        agent._thin_family_selection = None
        agent._direct_bypass_active = False
        agent._phased_runbook_receipt = None
        agent._use_phased_runbook = False
        agent._runbook_path = RUNBOOK
        agent._write_remote_text = AsyncMock()
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(return_code=0, stdout="{}", stderr="")
        )
        agent._run_id = lambda environment: "run-test"
        agent._statem_env = lambda run_id: {}
        agent.logs_dir = Path(tempfile.gettempdir()) / "v4p76-test-logs"
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

    def test_solver_gets_direction_verify_gets_acceptance_and_reviewer_gets_detail(
        self,
    ) -> None:
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
        overlay, _ = build_phased_runbook_overlay(RUNBOOK, selection, CATALOG)
        verify_text = overlay["nodes"]["verify"]["prompt"]
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertIn("Preserve exact public semantics", solver_text)
        self.assertNotIn("fixed representative population", solver_text)
        self.assertIn("fixed representative population", verify_text)
        self.assertNotIn("paired_measurement_validity", solver_text)
        self.assertNotIn("paired_measurement_validity", verify_text)
        self.assertIn(
            "paired_measurement_validity",
            reviewer["detailed"]["prioritized_checks"],
        )

    def test_semantic_translation_practice_is_thin_and_reviewer_scoped(self) -> None:
        instruction = (
            "Repair translator soundness while preserving source semantic "
            "equivalence on the default consumer path."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="shadow",
        )
        self.assertEqual(selection["practice_id"], "defined_semantics_boundary_matrix")
        agent = self._agent(practice_id="defined_semantics_boundary_matrix")
        selection["activated"] = True
        agent._thin_family_selection = selection
        solver_text = agent._augment_instruction(
            instruction,
            "run-semantic",
            "Run: run-semantic\nCurrent: solve\nNext: verify",
        )
        overlay, receipt = build_phased_runbook_overlay(RUNBOOK, selection, CATALOG)
        verify_text = overlay["nodes"]["verify"]["prompt"]
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertIn("source-to-target semantic mapping", solver_text)
        self.assertNotIn("paired safe and counterexample cases", solver_text)
        self.assertIn("paired safe and counterexample cases", verify_text)
        self.assertNotIn("source_target_semantic_equivalence", solver_text)
        self.assertNotIn("source_target_semantic_equivalence", verify_text)
        self.assertIn(
            "source_target_semantic_equivalence",
            reviewer["detailed"]["prioritized_checks"],
        )
        for forbidden in ("fresh", "adapted", "portfolio", "scoring lane"):
            self.assertNotIn(forbidden, solver_text.lower())
            self.assertNotIn(forbidden, verify_text.lower())
        self.assertEqual(
            receipt["nodes"], ["handoff", "self_review", "solve", "verify"]
        )
        self.assertEqual(receipt["edge_count"], 6)

    def test_projection_uses_character_budget_without_an_item_limit(self) -> None:
        instruction = (
            "Repair translator soundness while preserving source semantic "
            "equivalence on the default consumer path."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="shadow",
        )
        selection["activated"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = Path(temp_dir) / "catalog.json"
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            practice = next(
                item
                for item in data["practices"]
                if item["practice_id"] == "defined_semantics_boundary_matrix"
            )
            practice["compact"]["direction_cues"] = ["a", "b", "c", "d"]
            catalog.write_text(json.dumps(data), encoding="utf-8")
            selection["catalog_sha256"] = hashlib.sha256(
                catalog.read_bytes()
            ).hexdigest()
            projection = build_solver_projection(selection, "pre_solve", catalog)
        self.assertEqual(projection["obligations"], ["a", "b", "c", "d"])

    def test_projection_fails_closed_over_character_budget(self) -> None:
        instruction = (
            "Repair translator soundness while preserving source semantic "
            "equivalence on the default consumer path."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="shadow",
        )
        selection["activated"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = Path(temp_dir) / "catalog.json"
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            data["selection_policy"]["pre_solve_char_budget"] = 3
            catalog.write_text(json.dumps(data), encoding="utf-8")
            selection["catalog_sha256"] = hashlib.sha256(
                catalog.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "character budget"):
                build_solver_projection(selection, "pre_solve", catalog)

    def test_rendered_overlay_remains_a_strict_thin_graph(self) -> None:
        selection = select_thin_family_practice(
            "Improve graph search performance and cache scaling while preserving "
            "exact semantics.",
            CATALOG,
            activation_mode="active",
        )
        overlay, receipt = build_phased_runbook_overlay(RUNBOOK, selection, CATALOG)
        with tempfile.TemporaryDirectory() as temp_dir:
            rendered = Path(temp_dir) / "overlay.json"
            rendered.write_text(json.dumps(overlay), encoding="utf-8")
            spec = StatemSpec.load(rendered, strict=True)
        self.assertEqual(set(spec.nodes), {"solve", "verify", "self_review", "handoff"})
        self.assertEqual(len(spec.edges), receipt["edge_count"])

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
            ThinFamilyV4p76ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p76-exp",
        )


if __name__ == "__main__":
    unittest.main()
