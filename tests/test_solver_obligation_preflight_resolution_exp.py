from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integrations.harbor.experimental.artifact_identity import stable_sha256
from integrations.harbor.experimental.multirole_promotion_gate import (
    SOLVER_PLAN_FIELDS,
    _read_yaml,
    preflight_task,
    record_preflight_resolution,
    record_proposal,
    record_review_profile,
    record_solver_obligations,
    record_solver_plan,
    require_preflight_binding,
    seal_contract,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4p54ExperimentalStatemCodex,
    EvidenceDevelopV4p55ExperimentalStatemCodex,
)
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]


class SolverObligationPreflightResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.module = self.app / "worker.py"
        self.module.write_text("def transform(value):\n    return value\n", encoding="utf-8")
        self.task = self.root / "task.txt"
        self.task.write_text(
            "Repair transform while preserving the public callable.\n",
            encoding="utf-8",
        )
        self.state_dir = self.root / "state"
        self.run_id = "solver-obligation-test"
        self.env = {
            "STATEM_STATE_DIR": str(self.state_dir),
            "STATEM_RUN_ID": self.run_id,
            "STATEM_AGENT_ID": "lead-solver",
            "STATEM_AGENT_ROLE": "solver",
        }
        self.catalog = _read_yaml(REPO / "examples/reviewer-practice-router-v1.yaml")
        self.practices = _read_yaml(REPO / "examples/reviewer-practices-v1.yaml")

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

    def _contract_receipts(self) -> tuple[dict, dict, dict]:
        self._state("contract_audit", "contract-entry")
        with patch.dict("os.environ", self.env, clear=False):
            seal = seal_contract(
                artifact_root=self.app,
                contract_sources=[self.task],
                contract_policy="repair_aware",
            )
            profile = record_review_profile(
                draft={
                    "primary": "parsing-transformation",
                    "secondary": ["performance-resources"],
                    "evidence": ["the public callable transforms structured input"],
                },
                catalog=self.catalog,
                catalog_root=REPO / "examples",
                seal=seal,
            )
            obligations = record_solver_obligations(
                review_profile=profile,
                review_practices=self.practices,
            )
        return seal, profile, obligations

    @staticmethod
    def _plan_draft(obligations: dict) -> dict:
        return {
            "objective": "repair the implementation without public contract drift",
            "steps": ["inspect the public boundary", "implement the smallest repair"],
            "assumptions": [],
            "planned_checks": ["exercise public roundtrip and malformed input"],
            "mutation_scope": ["worker implementation body only"],
            "success_criteria": ["public consumer behavior passes without regression"],
            "obligation_coverage": [
                {
                    "obligation_id": item["obligation_id"],
                    "plan_sections": ["planned_checks", "success_criteria"],
                    "rationale": "the public checks and success criteria cover this obligation",
                }
                for item in obligations["obligations"]
            ],
        }

    def _solve_receipts(self, *, verdict: str) -> tuple[dict, dict, dict, dict, dict]:
        seal, profile, obligations = self._contract_receipts()
        self._state("solve", "solve-entry")
        draft = self._plan_draft(obligations)
        with patch.dict("os.environ", self.env, clear=False):
            plan = record_solver_plan(
                draft=draft,
                seal=seal,
                review_profile=profile,
                solver_obligations=obligations,
            )
        evidence = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": "solve-entry",
            "producer": {"agent_id": "preflight", "role": "preflight-reviewer"},
            "advisory_verdict": verdict,
            "plan_sha256": stable_sha256(plan),
            "contract_seal_sha256": stable_sha256(seal),
            "context_view_sha256": "c" * 64,
            "review_profile_sha256": stable_sha256(profile),
            "plan_findings": (
                ["the malformed-input boundary is absent"]
                if verdict == "revise_plan"
                else []
            ),
            "checklist_gaps": [],
            "assumption_risks": [],
            "recommendations": [],
            "contract_ledger": {
                "hard_constraints": [],
                "defeasible_claims": [],
                "conflicts_requiring_probes": [],
                "repair_implications": [],
            },
            "review_execution_class": "contract_language",
            "acceptance_plan": {"requirements": []},
            "promotion_authority": False,
        }
        return seal, profile, obligations, plan, evidence

    def test_projection_is_compact_and_plan_must_cover_every_id(self) -> None:
        seal, profile, obligations = self._contract_receipts()
        ids = [item["obligation_id"] for item in obligations["obligations"]]
        self.assertIn("practice:contract_authority_and_repair", ids)
        self.assertIn(
            "profile:parsing-transformation:preservation_obligations", ids
        )
        self.assertIn("profile:performance-resources:secondary-scope", ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("adversarial_probe_selection", ids)
        for item in obligations["obligations"]:
            self.assertTrue(item["invariant"])
            self.assertTrue(item["required_action"])
            self.assertTrue(item["self_check"])
        common = next(
            item
            for item in obligations["obligations"]
            if item["obligation_id"] == "practice:contract_authority_and_repair"
        )
        self.assertIn("Task-visible requirements", common["invariant"])
        primary = next(
            item
            for item in obligations["obligations"]
            if item["obligation_id"]
            == "profile:parsing-transformation:preservation_obligations"
        )
        self.assertIn("Define preservation obligations", primary["required_action"])
        serialized = json.dumps(obligations["obligations"])
        self.assertNotIn("counterexample_prioritization\"", serialized)
        self.assertNotIn("causal_verdict_calibration\"", serialized)

        self._state("solve", "solve-entry")
        draft = self._plan_draft(obligations)
        with patch.dict("os.environ", self.env, clear=False):
            plan = record_solver_plan(
                draft=draft,
                seal=seal,
                review_profile=profile,
                solver_obligations=obligations,
            )
        self.assertEqual(
            plan["solver_obligations_sha256"], stable_sha256(obligations)
        )

        incomplete = copy.deepcopy(draft)
        incomplete["obligation_coverage"].pop()
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "every projected obligation"):
                record_solver_plan(
                    draft=incomplete,
                    seal=seal,
                    review_profile=profile,
                    solver_obligations=obligations,
                )

    def test_v4p54_identity_and_runbook_bind_the_new_controls(self) -> None:
        runbook = REPO / "examples/frontier-bench-agent-evidence-develop-v4p54-exp.yaml"
        agent = EvidenceDevelopV4p54ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p54ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = runbook
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600

        instruction = agent._augment_instruction("task", "run", "context")
        self.assertTrue(validate_spec(str(runbook), strict=True)["ok"])
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p54-exp",
        )
        self.assertIn("solver-obligations.json", instruction)
        self.assertIn("preflight-resolution.json", instruction)
        text = runbook.read_text(encoding="utf-8")
        self.assertIn("solver-obligations", text)
        self.assertIn("--preflight-resolution", text)

    def test_v4p55_identity_and_runbook_bind_role_boundary_controls(self) -> None:
        runbook = REPO / "examples/frontier-bench-agent-evidence-develop-v4p55-exp.yaml"
        agent = EvidenceDevelopV4p55ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4p55ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = runbook
        agent._reviewer_timeout_seconds = 900
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "high"
        agent._preflight_reviewer_timeout_seconds = 480
        agent._preflight_reviewer_reasoning_effort = "medium"
        agent._preflight_reviewer_lease_seconds = 3600

        instruction = agent._augment_instruction("task", "run", "context")
        self.assertTrue(validate_spec(str(runbook), strict=True)["ok"])
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4p55-exp",
        )
        self.assertIn("invariant, required_action, and self_check", instruction)
        self.assertIn("mechanically invalid assessment", instruction)
        text = runbook.read_text(encoding="utf-8")
        self.assertIn("bounded_text_fields", text)
        self.assertIn("max_text_chars", text)

    def test_legacy_plan_and_preflight_task_shape_remain_unchanged(self) -> None:
        seal, profile, _ = self._contract_receipts()
        self._state("solve", "solve-entry")
        legacy_draft = {
            "objective": "repair the implementation",
            "steps": ["inspect and repair"],
            "assumptions": [],
            "planned_checks": ["exercise the public callable"],
            "mutation_scope": ["implementation body"],
            "success_criteria": ["public behavior is correct"],
        }
        with patch.dict("os.environ", self.env, clear=False):
            plan = record_solver_plan(
                draft=legacy_draft,
                seal=seal,
                review_profile=profile,
            )
            view = {
                "version": 1,
                "kind": "context_view",
                "run_id": self.run_id,
                "node": "solve",
                "entry_id": "solve-entry",
                "producer": {"agent_id": "hook", "role": "stateful_hook"},
                "consumer_role": "preflight_reviewer",
                "included": [],
            }
            task = preflight_task(
                plan=plan,
                seal=seal,
                context_view=view,
                review_profile=profile,
            )
        self.assertNotIn("solver_obligations_sha256", plan)
        self.assertNotIn("obligation_coverage", plan)
        self.assertNotIn("solver_obligations", task["tasks"][0])

    def test_ready_preflight_gets_host_owned_not_required_resolution(self) -> None:
        _, _, obligations, plan, evidence = self._solve_receipts(verdict="ready")
        with patch.dict("os.environ", self.env, clear=False):
            resolution = record_preflight_resolution(
                draft=None,
                plan=plan,
                preflight_evidence=evidence,
                solver_obligations=obligations,
            )
        self.assertEqual(resolution["status"], "not_required")
        self.assertEqual(resolution["effective_plan_sha256"], stable_sha256(plan))

    def test_revise_plan_requires_real_changed_sections_and_proposal_binding(self) -> None:
        seal, _, obligations, plan, evidence = self._solve_receipts(
            verdict="revise_plan"
        )
        with patch.dict("os.environ", self.env, clear=False):
            template = record_preflight_resolution(
                draft=None,
                plan=plan,
                preflight_evidence=evidence,
                solver_obligations=obligations,
            )
        self.assertEqual(template["status"], "draft_required")
        self.assertEqual(len(template["issue_ids"]), 1)

        revised_plan = {
            field: copy.deepcopy(plan[field])
            for field in (*sorted(SOLVER_PLAN_FIELDS), "obligation_coverage")
        }
        revised_plan["planned_checks"].append(
            "exercise a malformed-input boundary through the public consumer"
        )
        draft = {
            "revised_plan": revised_plan,
            "issue_resolutions": [
                {
                    "issue_id": template["issue_ids"][0],
                    "plan_section": "planned_checks",
                    "resolution": "added the missing malformed-input boundary check",
                }
            ],
        }
        with patch.dict("os.environ", self.env, clear=False):
            resolution = record_preflight_resolution(
                draft=draft,
                plan=plan,
                preflight_evidence=evidence,
                solver_obligations=obligations,
            )
        self.assertEqual(resolution["status"], "revised")
        self.assertNotEqual(
            resolution["effective_plan_sha256"], stable_sha256(plan)
        )

        self.module.write_text(
            "def transform(value):\n    return value + 1\n", encoding="utf-8"
        )
        proposal_draft = {
            "target_gap": "the public transform is incomplete",
            "hypothesis": "the implementation omits the required transform",
            "counter_hypothesis": "the public behavior is already complete",
            "protected_behavior": ["the public callable remains compatible"],
            "protected_behavior_basis": [
                {
                    "behavior": "the public callable remains compatible",
                    "basis": "public_signature",
                    "evidence": "the visible callable signature is unchanged",
                }
            ],
            "discriminating_checks": ["exercise the public consumer boundary"],
            "rollback_artifact_identity": seal["baseline_artifact_identity"],
            "rollback_locator": "snapshot://baseline",
        }
        with patch.dict("os.environ", self.env, clear=False):
            proposal = record_proposal(
                draft=proposal_draft,
                seal=seal,
                artifact_root=self.app,
                preflight_evidence=evidence,
                solver_plan=plan,
                preflight_resolution=resolution,
            )
            require_preflight_binding(
                proposal=proposal,
                preflight_evidence=evidence,
                solver_plan=plan,
                preflight_resolution=resolution,
            )
        self.assertEqual(proposal["solver_plan_sha256"], stable_sha256(plan))
        self.assertEqual(
            proposal["preflight_resolution_sha256"], stable_sha256(resolution)
        )

        unchanged = copy.deepcopy(revised_plan)
        unchanged["planned_checks"] = copy.deepcopy(plan["planned_checks"])
        unchanged["steps"].append("retain an unrelated implementation note")
        invalid = {**draft, "revised_plan": unchanged}
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "unchanged plan section"):
                record_preflight_resolution(
                    draft=invalid,
                    plan=plan,
                    preflight_evidence=evidence,
                    solver_obligations=obligations,
                )


if __name__ == "__main__":
    unittest.main()
