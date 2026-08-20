from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from integrations.harbor.experimental.artifact_identity import artifact_identity
from integrations.harbor.experimental.develop_family_router import select_family
from integrations.harbor.experimental.failure_feedback_gate import (
    prepare_retry_brief,
    validate_preflight_delta,
)
from integrations.harbor.experimental.recovering_develop_guard import (
    close_cycle,
    open_cycle,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p31ExperimentalStatemCodex,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4p31-exp.yaml"
FAMILY_CATALOG = REPO / "examples/develop-family-router-v1.yaml"


class FailureClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "worker.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.ledger = self.root / "cycle-ledger.json"
        self.deadline = self.root / "deadline.json"
        self.run_id = "failure-closure-test"
        self.env = {
            "STATEM_RUN_ID": self.run_id,
            "STATEM_STATE_DIR": str(self.state_dir),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _state(self, node: str, entry_id: str) -> None:
        path = self.state_dir / "runs" / self.run_id / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "current": node,
                    "current_entry_id": entry_id,
                }
            ),
            encoding="utf-8",
        )

    def _seal(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "contract_seal",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-1",
            "baseline_artifact_identity": artifact_identity(self.app),
        }

    def _application(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "artifact_application_verification",
            "run_id": self.run_id,
            "node": "promote",
            "entry_id": "promote-1",
            "observed_artifact_identity": artifact_identity(self.app),
            "verified": True,
        }

    def _family(self, reserve: int = 2100) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "develop_family_selection",
            "family_id": "structured-transformation",
            "retry_reserve_seconds": reserve,
        }

    def _replay(self, *, owner: str = "lead_solver") -> dict[str, object]:
        evidence = "public replay exposed an encoded boundary mismatch"
        rationale = "append the exact encoded boundary to independent acceptance"
        return {
            "status": "recoverable_failure",
            "evidence": [evidence],
            "residual_risk": [],
            "next_gap": "repair the encoded boundary handling",
            "failure_ownership": {
                "failure_class": "implementation_defect",
                "owner_role": owner,
                "observed_failure": evidence,
                "causal_hypothesis": "the candidate normalizes before classifying the boundary",
                "repair_action": "repair the encoded boundary handling",
                "required_validation_update": rationale,
                "confidence": "high",
            },
            "validation_delta": {
                "action": "append_regression",
                "discriminating_check": "replay literal and encoded boundary pairs on the public consumer",
                "success_interpretation": "only the contract-defined dangerous form is rejected",
                "failure_interpretation": "the repair still conflates literal and encoded forms",
                "preserves_prior_obligations": True,
                "superseded_check_ids": [],
                "rationale": rationale,
            },
            "hard_gap_resolutions": [],
        }

    def _open(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(ledger_path=self.ledger, seal=self._seal(), max_cycles=2)

    def test_family_selection_is_deterministic_from_primary_profile(self) -> None:
        catalog = yaml.safe_load(FAMILY_CATALOG.read_text(encoding="utf-8"))
        profile = {
            "version": 1,
            "kind": "review_profile_selection",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-1",
            "primary": "parsing-transformation",
            "secondary": ["security-protocols", "stateful-systems"],
        }
        selected = select_family(catalog=catalog, review_profile=profile)
        self.assertEqual(selected["family_id"], "structured-transformation")
        self.assertEqual(selected["retry_reserve_seconds"], 2100)

    def test_deadline_gate_requires_a_complete_family_cycle_reserve(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 1200}),
            encoding="utf-8",
        )
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=self._replay(),
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "handoff")
        self.assertTrue(decision["information_gain_authorized"])
        self.assertTrue(decision["failure_owner_authorized"])
        self.assertFalse(decision["deadline_feasible"])
        self.assertEqual(decision["deadline_reason"], "insufficient_full_cycle_reserve")

    def test_deadline_gate_allows_a_complete_family_cycle(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 3600}),
            encoding="utf-8",
        )
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=self._replay(),
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "retry")
        self.assertTrue(decision["information_gain_authorized"])
        self.assertTrue(decision["failure_owner_authorized"])
        self.assertTrue(decision["deadline_feasible"])
        self.assertEqual(decision["deadline_reason"], "full_cycle_reserve_available")

    def test_adapter_owned_failure_hands_off_without_consuming_a_cycle(self) -> None:
        self._open()
        self.deadline.write_text(
            json.dumps({"deadline_at_epoch": time.time() + 3600}),
            encoding="utf-8",
        )
        replay = self._replay()
        rationale = "repair the evidence projector before another task-agent cycle"
        replay["failure_ownership"] = {
            "failure_class": "evidence_projection_gap",
            "owner_role": "adapter",
            "observed_failure": replay["evidence"][0],
            "causal_hypothesis": "the projector omitted a public artifact field",
            "repair_action": replay["next_gap"],
            "required_validation_update": rationale,
            "confidence": "high",
        }
        replay["validation_delta"] = {
            "action": "no_public_delta",
            "discriminating_check": "re-export the same public evidence after projector repair",
            "success_interpretation": "the existing evidence is represented completely",
            "failure_interpretation": "the projector remains incomplete",
            "preserves_prior_obligations": True,
            "superseded_check_ids": [],
            "rationale": rationale,
        }
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=replay,
                application=self._application(),
                artifact_root=self.app,
                require_information_gain=True,
                require_failure_closure=True,
                deadline_path=self.deadline,
                family_selection=self._family(),
            )
        self.assertEqual(decision["action"], "handoff")
        self.assertFalse(decision["information_gain_authorized"])
        self.assertFalse(decision["failure_owner_authorized"])
        self.assertTrue(decision["deadline_feasible"])

    def test_failure_owner_mapping_is_host_validated(self) -> None:
        self._open()
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "must be owned by 'lead_solver'"):
                close_cycle(
                    ledger_path=self.ledger,
                    replay_draft=self._replay(owner="test_planner"),
                    application=self._application(),
                    artifact_root=self.app,
                    require_information_gain=True,
                    require_failure_closure=True,
                    deadline_path=self.deadline,
                    family_selection=self._family(),
                )

    def test_validation_delta_is_carried_into_next_candidate_blind_plan(self) -> None:
        replay = self._replay()
        decision = {
            "version": 1,
            "kind": "recovering_develop_replay_decision",
            "action": "retry",
            "failure_ownership": replay["failure_ownership"],
            "validation_delta": replay["validation_delta"],
        }
        brief = prepare_retry_brief(decision)
        check = replay["validation_delta"]["discriminating_check"]
        preflight = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "encoded_boundary_regression",
                        "required_strata": [check],
                    }
                ]
            },
        }
        receipt = validate_preflight_delta(
            brief=brief,
            preflight_evidence=preflight,
        )
        self.assertTrue(receipt["applied"])
        self.assertEqual(
            receipt["matched_requirement_ids"], ["encoded_boundary_regression"]
        )

        preflight["acceptance_plan"]["requirements"][0]["required_strata"] = [
            "an unrelated check"
        ]
        with self.assertRaisesRegex(ValueError, "did not append the exact"):
            validate_preflight_delta(brief=brief, preflight_evidence=preflight)

    def test_v4p31_adapter_and_runbook_are_versioned_and_valid(self) -> None:
        agent = EvidenceDevelopV4p31ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p31ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = RUNBOOK
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("develop_family_router.py", names)
        self.assertIn("develop-family-router-v1.yaml", names)
        self.assertIn("failure_feedback_gate.py", names)
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p31-exp",
        )
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600
        instruction = agent._augment_instruction("task", "run", "context")
        self.assertIn("family/family-selection.json", instruction)
        self.assertIn("recovering-develop/retry-brief.json", instruction)
        validate_spec(RUNBOOK, strict=True)


if __name__ == "__main__":
    unittest.main()
