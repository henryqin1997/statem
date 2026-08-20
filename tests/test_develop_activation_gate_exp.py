from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integrations.harbor.experimental.artifact_identity import stable_sha256
from integrations.harbor.experimental.develop_activation_gate import decide_activation


class DevelopActivationGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = self.root / "task.txt"
        self.task.write_text("Repair the public callable.\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.run_id = "activation-test"
        state = self.state_dir / "runs" / self.run_id / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "current": "contract_audit",
                    "current_entry_id": "contract-1",
                }
            ),
            encoding="utf-8",
        )
        self.env = {
            "STATEM_RUN_ID": self.run_id,
            "STATEM_STATE_DIR": str(self.state_dir),
        }
        self.seal = {
            "version": 1,
            "kind": "contract_seal",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-1",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _draft(self, **updates) -> dict[str, object]:
        draft: dict[str, object] = {
            "recommended_route": "direct_solve",
            "contract_ambiguity": "low",
            "mutation_risk": "low",
            "state_or_resource_risk": "low",
            "quantitative_acceptance": False,
            "public_checks_available": True,
            "semantic_forks": [],
            "reasons": ["one localized public repair with a direct public check"],
        }
        draft.update(updates)
        return draft

    def test_shadow_mode_records_direct_eligibility_without_changing_route(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            receipt = decide_activation(
                draft=self._draft(),
                task_path=self.task,
                seal=self.seal,
                mode="shadow",
            )
        self.assertTrue(receipt["direct_eligible"])
        self.assertEqual(receipt["host_route"], "direct_solve")
        self.assertEqual(receipt["effective_route"], "evidence_develop")
        self.assertEqual(receipt["contract_seal_sha256"], stable_sha256(self.seal))

    def test_host_forces_evidence_for_any_material_risk(self) -> None:
        cases = (
            {"contract_ambiguity": "medium"},
            {"mutation_risk": "high"},
            {"state_or_resource_risk": "medium"},
            {"quantitative_acceptance": True},
            {"public_checks_available": False},
            {"semantic_forks": ["two plausible estimator variants"]},
            {"recommended_route": "evidence_develop"},
        )
        for update in cases:
            with self.subTest(update=update), patch.dict(
                os.environ, self.env, clear=False
            ):
                receipt = decide_activation(
                    draft=self._draft(**update),
                    task_path=self.task,
                    seal=self.seal,
                    mode="enforce",
                )
            self.assertFalse(receipt["direct_eligible"])
            self.assertEqual(receipt["effective_route"], "evidence_develop")


if __name__ == "__main__":
    unittest.main()
