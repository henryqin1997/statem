from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from integrations.harbor.experimental.artifact_identity import (
    artifact_identity,
    stable_sha256,
)
from integrations.harbor.experimental.multirole_promotion_gate import (
    _read_yaml,
    _context_bundle,
    canonicalize_falsifier_result,
    decide_promotion,
    falsifier_task,
    main as promotion_gate_main,
    preflight_task,
    record_review_profile,
    record_acceptance_evidence,
    record_context_view,
    record_preflight_evidence,
    record_proposal,
    record_solver_plan,
    require_preflight_binding,
    seal_contract,
    verify_application,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4ExperimentalStatemCodex,
    MultiRoleDevelopExperimentalStatemCodex,
)
from integrations.teamrun.teamrun_codex_worker import (
    _build_instruction,
    _run_codex,
)


REPO = Path(__file__).resolve().parents[1]


class MultiRolePromotionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.module = self.app / "worker.py"
        self.baseline_text = (
            '"""Public worker contract."""\n\n'
            "def transform(value: int) -> int:\n"
            '    """Return the transformed value."""\n'
            "    return value\n"
        )
        self.module.write_text(self.baseline_text, encoding="utf-8")
        self.task = self.root / "task.txt"
        self.task.write_text("Repair transform while preserving its interface.\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.run_id = "multirole-test"
        self.agent_id = "lead-solver"
        self.env = {
            "STATEM_STATE_DIR": str(self.state_dir),
            "STATEM_RUN_ID": self.run_id,
            "STATEM_AGENT_ID": self.agent_id,
            "STATEM_AGENT_ROLE": "solver",
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

    def _receipts(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        self._state("contract_audit", "contract-entry")
        with patch.dict("os.environ", self.env, clear=False):
            seal = seal_contract(artifact_root=self.app, contract_sources=[self.task])

        self.module.write_text(
            self.baseline_text.replace("return value\n", "return value + 1\n"),
            encoding="utf-8",
        )
        self._state("solve", "solve-entry")
        draft = {
            "target_gap": "transform returns the unmodified value",
            "hypothesis": "the implementation omits the required increment",
            "counter_hypothesis": "the public contract expects identity behavior",
            "protected_behavior": ["the public signature and docstring remain stable"],
            "protected_behavior_basis": [
                {
                    "behavior": "the public signature and docstring remain stable",
                    "basis": "public_signature",
                    "evidence": "the public transform signature is visible in the baseline",
                }
            ],
            "discriminating_checks": ["exercise zero, positive, and negative values"],
            "rollback_artifact_identity": seal["baseline_artifact_identity"],
            "rollback_locator": "snapshot://baseline",
        }
        with patch.dict("os.environ", self.env, clear=False):
            proposal = record_proposal(draft=draft, seal=seal, artifact_root=self.app)

        self._state("falsify", "falsify-entry")
        with patch.dict("os.environ", self.env, clear=False):
            view = record_context_view(
                role="falsifier",
                included_paths=[self.app, self.task],
            )
        return seal, proposal, view

    def _falsifier(
        self,
        seal: dict[str, object],
        proposal: dict[str, object],
        view: dict[str, object],
        **overrides: object,
    ) -> dict[str, object]:
        raw: dict[str, object] = {
            "status": "completed",
            "summary": "counter-hypothesis was exercised independently",
            "claims": ["candidate matches the visible increment behavior"],
            "evidence": ["public transform replay covered boundary values"],
            "coverage": {"complete": True},
            "children": [],
            "prune_proposals": [],
            "verdict": "accept",
            "candidate_artifact_identity": proposal["candidate_artifact_identity"],
            "contract_seal_sha256": stable_sha256(seal),
            "context_view_sha256": stable_sha256(view),
            "contract_preserved": True,
            "regressions": [],
            "contract_violations": [],
            "counterevidence": ["identity behavior was tested and rejected"],
        }
        raw.update(overrides)
        return {
            "version": 1,
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-entry",
            "producer": {"agent_id": "independent-reviewer", "role": "falsifier"},
            "status": raw["status"],
            "claims": raw["claims"],
            "evidence": raw["evidence"],
            "coverage": raw["coverage"],
            "raw": raw,
        }

    def test_decide_cli_reuses_semantically_identical_receipt(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        paths = {
            "seal": self.root / "seal.json",
            "proposal": self.root / "proposal.json",
            "view": self.root / "view.json",
            "falsifier": self.root / "falsifier.json",
            "decision": self.root / "decision.json",
        }
        for name, value in (
            ("seal", seal),
            ("proposal", proposal),
            ("view", view),
            ("falsifier", falsifier),
        ):
            paths[name].write_text(json.dumps(value), encoding="utf-8")
        argv = [
            "decide",
            "--seal",
            str(paths["seal"]),
            "--proposal",
            str(paths["proposal"]),
            "--context-view",
            str(paths["view"]),
            "--falsifier-result",
            str(paths["falsifier"]),
            "--artifact-root",
            str(self.app),
            "--output",
            str(paths["decision"]),
        ]
        with patch.dict("os.environ", self.env, clear=False):
            with patch(
                "integrations.harbor.experimental.multirole_promotion_gate._now",
                return_value="2026-08-15T00:00:00Z",
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(promotion_gate_main(argv), 0)
        first_bytes = paths["decision"].read_bytes()

        with patch.dict("os.environ", self.env, clear=False):
            with patch(
                "integrations.harbor.experimental.multirole_promotion_gate._now",
                return_value="2026-08-15T00:01:00Z",
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(promotion_gate_main(argv), 0)
        self.assertEqual(paths["decision"].read_bytes(), first_bytes)
        self.assertEqual(
            json.loads(first_bytes)["created_at"],
            "2026-08-15T00:00:00Z",
        )

        falsifier["raw"]["verdict"] = "inconclusive"
        paths["falsifier"].write_text(json.dumps(falsifier), encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            with patch(
                "integrations.harbor.experimental.multirole_promotion_gate._now",
                return_value="2026-08-15T00:02:00Z",
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(promotion_gate_main(argv), 0)
        changed = json.loads(paths["decision"].read_text(encoding="utf-8"))
        self.assertEqual(changed["created_at"], "2026-08-15T00:02:00Z")
        self.assertNotEqual(paths["decision"].read_bytes(), first_bytes)

    def test_preflight_is_advisory_entry_bound_and_required_by_proposal(self) -> None:
        self._state("contract_audit", "contract-entry")
        with patch.dict("os.environ", self.env, clear=False):
            seal = seal_contract(artifact_root=self.app, contract_sources=[self.task])
        profile = {
            "version": 1,
            "kind": "review_profile_selection",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": "contract-entry",
            "producer": {"agent_id": self.agent_id, "role": "solver"},
            "contract_seal_sha256": stable_sha256(seal),
            "primary": "algorithm_semantics",
            "secondary": [],
            "evidence": ["the task repairs a named transformation"],
            "documents": [],
        }
        self._state("solve", "solve-entry")
        with patch.dict("os.environ", self.env, clear=False):
            plan = record_solver_plan(
                draft={
                    "objective": "repair transform without changing its interface",
                    "steps": ["inspect the public implementation", "apply the smallest repair"],
                    "assumptions": ["the public signature is a hard constraint"],
                    "planned_checks": ["exercise zero, positive, and negative values"],
                    "mutation_scope": ["worker.py implementation body"],
                    "success_criteria": ["public checks pass with the signature unchanged"],
                },
                seal=seal,
                review_profile=profile,
            )
        plan_file = self.root / "solver-plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            view = record_context_view(
                role="preflight_reviewer",
                included_paths=[self.task, plan_file],
            )
            task = preflight_task(
                plan=plan,
                seal=seal,
                context_view=view,
                review_profile=profile,
            )
        assignment = task["tasks"][0]
        self.assertIn("authorize promotion", assignment["assignment"])
        self.assertEqual(
            assignment["contract_ledger_schema"]["item_fields"][
                "hard_constraints"
            ],
            ["claim", "basis", "evidence"],
        )
        self.assertIn("Do not invent aliases", assignment["assignment"])
        self.assertEqual(assignment["review_execution_class"], "contract_language")
        self.assertEqual(
            assignment["acceptance_plan_schema"]["candidate_visibility"], "none"
        )
        self.assertEqual(
            assignment["acceptance_plan_schema"]["required_top_level_fields"],
            ["requirements"],
        )
        self.assertIn(
            "selection_basis",
            assignment["acceptance_plan_schema"]["requirement_fields"],
        )
        self.assertIn(
            "uncovered_regions",
            assignment["acceptance_plan_schema"]["requirement_fields"],
        )
        self.assertNotIn(
            "adapter_replay_mapping_required",
            assignment["acceptance_plan_schema"],
        )
        raw = {
            "status": "completed",
            "summary": "the plan covers the visible contract",
            "claims": ["the planned public probes distinguish the stated hypotheses"],
            "evidence": ["the mutation scope is limited to the implementation body"],
            "coverage": {"complete": True},
            "children": [],
            "prune_proposals": [],
            "advisory_verdict": "ready",
            "plan_sha256": stable_sha256(plan),
            "contract_seal_sha256": stable_sha256(seal),
            "context_view_sha256": stable_sha256(view),
            "review_profile_sha256": stable_sha256(profile),
            "plan_findings": [],
            "checklist_gaps": [],
            "assumption_risks": [],
            "recommendations": ["retain the public signature check"],
            "review_execution_class": "contract_language",
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "PUBLIC-BOUNDARIES",
                        "claim": "the public transform handles boundary values",
                        "public_surface": "the public transform callable",
                        "evidence_mode": "adapter_replay",
                        "support_dimensions": ["input sign and zero boundary"],
                        "required_strata": ["negative", "zero", "positive"],
                        "selection_basis": "the public numeric domain and zero boundary",
                        "uncovered_regions": ["none"],
                        "independence_basis": "selected before a candidate exists",
                        "rationale": "the stated behavior differs at these boundaries",
                    },
                    {
                        "requirement_id": "SIGNATURE-PRESERVATION",
                        "claim": "the public signature remains compatible",
                        "public_surface": "the callable signature",
                        "evidence_mode": "paired_review",
                        "support_dimensions": ["parameter and return contract"],
                        "required_strata": ["baseline", "candidate"],
                        "selection_basis": "the public callable signature",
                        "uncovered_regions": ["none"],
                        "independence_basis": "paired baseline and candidate inspection",
                        "rationale": "signature drift is a protected-interface concern",
                    },
                ],
                "adapter_replay_mapping": [
                    {
                        "requirement_id": "PUBLIC-BOUNDARIES",
                        "public_surface": "the public transform callable",
                        "replay_observation": "observe negative, zero, and positive",
                    }
                ],
            },
            "contract_ledger": {
                "hard_constraints": [
                    {
                        "claim": "  the public transform signature remains stable  ",
                        "basis": "public_signature",
                        "evidence": "the public callable is part of the visible interface",
                    }
                ],
                "defeasible_claims": [
                    {
                        "claim": "the starter implementation is identity behavior",
                        "source": "broken starter implementation",
                        "reason": "the task explicitly asks for repair",
                    }
                ],
                "conflicts_requiring_probes": [],
                "repair_implications": [
                    {
                        "scope": "worker.py implementation body",
                        "preserve": "public signature",
                        "verify": "replay zero, positive, and negative values",
                    }
                ],
            },
        }
        reviewer_result = {
            "version": 1,
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": "solve-entry",
            "task_id": "preflight_plan_review",
            "producer": {"agent_id": "preflight-1", "role": "preflight-reviewer"},
            "submitted_at": "2026-08-14T00:00:00Z",
            "status": "completed",
            "coverage": {"complete": True},
            "raw": raw,
        }
        with patch.dict("os.environ", self.env, clear=False):
            evidence = record_preflight_evidence(
                plan=plan,
                seal=seal,
                context_view=view,
                review_profile=profile,
                reviewer_result=reviewer_result,
            )
        self.assertFalse(evidence["promotion_authority"])
        self.assertEqual(
            evidence["contract_ledger"]["hard_constraints"][0]["basis"],
            "public_signature",
        )
        self.assertEqual(
            evidence["contract_ledger"]["hard_constraints"][0]["claim"],
            "the public transform signature remains stable",
        )
        self.assertEqual(
            evidence["acceptance_plan"]["requirements"][0]["requirement_id"],
            "public-boundaries",
        )
        self.assertEqual(
            evidence["acceptance_plan"]["requirements"][1]["requirement_id"],
            "signature-preservation",
        )
        self.assertEqual(evidence["review_execution_class"], "contract_language")
        self.assertEqual(
            evidence["schema_repairs"],
            [
                "requirements[0]:missing_claim_scope->bounded_acceptance",
                "requirements[1]:missing_claim_scope->bounded_acceptance",
                "discarded_non_authoritative_adapter_replay_mapping",
            ],
        )
        self.assertEqual(evidence["acceptance_plan_schema_version"], 1)
        self.assertEqual(set(evidence["acceptance_plan"]), {"requirements"})
        self.assertEqual(
            evidence["acceptance_plan"]["requirements"][0]["uncovered_regions"],
            ["none"],
        )
        v2_reviewer_result = json.loads(json.dumps(reviewer_result))
        v2_plan = v2_reviewer_result["raw"]["acceptance_plan"]
        del v2_plan["adapter_replay_mapping"]
        for requirement in v2_plan["requirements"]:
            requirement["claim_scope"] = "bounded_acceptance"
        with patch.dict("os.environ", self.env, clear=False):
            v2_evidence = record_preflight_evidence(
                plan=plan,
                seal=seal,
                context_view=view,
                review_profile=profile,
                reviewer_result=v2_reviewer_result,
            )
        self.assertEqual(v2_evidence["acceptance_plan_schema_version"], 2)
        self.assertEqual(v2_evidence["schema_repairs"], [])
        draft = {
            "target_gap": "transform returns the unmodified value",
            "hypothesis": "the implementation omits the required increment",
            "counter_hypothesis": "the public contract expects identity behavior",
            "protected_behavior": ["the public signature remains stable"],
            "discriminating_checks": ["exercise zero, positive, and negative values"],
            "rollback_artifact_identity": seal["baseline_artifact_identity"],
            "rollback_locator": "snapshot://baseline",
        }
        with patch.dict("os.environ", self.env, clear=False):
            proposal = record_proposal(
                draft=draft,
                seal=seal,
                artifact_root=self.app,
                preflight_evidence=evidence,
            )
        self.assertEqual(
            proposal["preflight_evidence_sha256"], stable_sha256(evidence)
        )
        require_preflight_binding(
            proposal=proposal,
            preflight_evidence=evidence,
            reviewer_result=reviewer_result,
        )

        raw_evidence = json.loads(json.dumps(evidence))
        derived_evidence = json.loads(json.dumps(raw_evidence))
        appended_check = "replay the retained public boundary packet"
        derived_evidence["acceptance_plan"]["requirements"][0][
            "required_strata"
        ].append(appended_check)
        derived_proposal = json.loads(json.dumps(proposal))
        derived_proposal["preflight_evidence_sha256"] = stable_sha256(
            derived_evidence
        )
        brief = {
            "version": 1,
            "kind": "failure_feedback_retry_brief",
            "required": True,
            "reason": "authorized_retry",
            "failure_closure_sha256": "f" * 64,
            "failure_ownership": {
                "failure_class": "acceptance_plan_gap",
                "owner_role": "test_planner",
                "observed_failure": "the boundary packet was absent",
                "causal_hypothesis": "the plan omitted a public discriminator",
                "repair_action": "append the retained boundary packet",
                "required_validation_update": "bind the retained packet",
                "confidence": "high",
            },
            "validation_delta": {
                "action": "append_regression",
                "discriminating_check": appended_check,
                "success_interpretation": "the public boundary behavior matches",
                "failure_interpretation": "the candidate still violates the boundary",
                "preserves_prior_obligations": True,
                "superseded_check_ids": [],
                "rationale": "bind the retained packet",
            },
            "created_at": "2026-08-14T00:01:00Z",
        }
        transition_feedback = {
            "version": 1,
            "kind": "transition_failure_feedback",
            "entry_id": raw_evidence["entry_id"],
            "current_state": raw_evidence["node"],
            "target_state": "falsify",
            "stage": "before_transfer",
            "blocker_fingerprint": "a" * 64,
            "repeat_count": 1,
            "repair_budget_exhausted": False,
            "failed_checks": [
                {
                    "failure_class": "acceptance_plan_gap",
                    "repair_owner": "test_planner",
                    "summary": "the exact retry discriminator is absent",
                }
            ],
        }
        transaction = {
            "version": 1,
            "kind": "canonical_preflight_repair_transaction",
            "status": "committed",
            "required": True,
            "append_only": True,
            "requirement_id": "public-boundaries",
            "failure_closure_sha256": brief["failure_closure_sha256"],
            "validation_delta_sha256": stable_sha256(brief["validation_delta"]),
            "brief_sha256": stable_sha256(brief),
            "transition_feedback_sha256": stable_sha256(transition_feedback),
            "blocker_fingerprint": transition_feedback["blocker_fingerprint"],
            "original_preflight_sha256": stable_sha256(raw_evidence),
            "draft_preflight_sha256": stable_sha256(derived_evidence),
            "canonical_preflight_sha256": stable_sha256(derived_evidence),
            "created_at": "2026-08-14T00:02:00Z",
        }
        transaction["receipt_sha256"] = stable_sha256(transaction)
        require_preflight_binding(
            proposal=derived_proposal,
            preflight_evidence=derived_evidence,
            reviewer_result=reviewer_result,
            raw_preflight_evidence=raw_evidence,
            repair_transaction=transaction,
            retry_brief=brief,
            transition_feedback=transition_feedback,
        )
        derived_paths = {
            name: self.root / f"derived-{name}.json"
            for name in (
                "proposal",
                "preflight",
                "raw",
                "transaction",
                "brief",
                "feedback",
            )
        }
        for name, payload in (
            ("proposal", derived_proposal),
            ("preflight", derived_evidence),
            ("raw", raw_evidence),
            ("transaction", transaction),
            ("brief", brief),
            ("feedback", transition_feedback),
        ):
            derived_paths[name].write_text(json.dumps(payload), encoding="utf-8")
        with (
            patch(
                "integrations.harbor.experimental.multirole_promotion_gate."
                "DEFAULT_RAW_PREFLIGHT_EVIDENCE",
                derived_paths["raw"],
            ),
            patch(
                "integrations.harbor.experimental.multirole_promotion_gate."
                "DEFAULT_PREFLIGHT_REPAIR_TRANSACTION",
                derived_paths["transaction"],
            ),
            patch(
                "integrations.harbor.experimental.multirole_promotion_gate."
                "DEFAULT_RETRY_BRIEF",
                derived_paths["brief"],
            ),
            patch(
                "integrations.harbor.experimental.multirole_promotion_gate."
                "DEFAULT_TRANSITION_FAILURE_FEEDBACK",
                derived_paths["feedback"],
            ),
            patch(
                "integrations.harbor.experimental.multirole_promotion_gate."
                "_load_current_role_result",
                return_value=reviewer_result,
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                promotion_gate_main(
                    [
                        "require-preflight",
                        "--proposal",
                        str(derived_paths["proposal"]),
                        "--preflight-evidence",
                        str(derived_paths["preflight"]),
                    ]
                ),
                0,
            )

        with self.assertRaisesRegex(ValueError, "immutable TeamRun payload"):
            require_preflight_binding(
                proposal=derived_proposal,
                preflight_evidence=derived_evidence,
                reviewer_result=reviewer_result,
            )

        rewritten_evidence = json.loads(json.dumps(derived_evidence))
        rewritten_evidence["acceptance_plan"]["requirements"][0][
            "claim"
        ] = "a rewritten claim"
        rewritten_proposal = json.loads(json.dumps(derived_proposal))
        rewritten_proposal["preflight_evidence_sha256"] = stable_sha256(
            rewritten_evidence
        )
        forged_transaction = json.loads(json.dumps(transaction))
        forged_transaction["draft_preflight_sha256"] = stable_sha256(
            rewritten_evidence
        )
        forged_transaction["canonical_preflight_sha256"] = stable_sha256(
            rewritten_evidence
        )
        forged_transaction["receipt_sha256"] = stable_sha256(
            {
                key: value
                for key, value in forged_transaction.items()
                if key != "receipt_sha256"
            }
        )
        with self.assertRaisesRegex(ValueError, "outside the authorized append"):
            require_preflight_binding(
                proposal=rewritten_proposal,
                preflight_evidence=rewritten_evidence,
                reviewer_result=reviewer_result,
                raw_preflight_evidence=raw_evidence,
                repair_transaction=forged_transaction,
                retry_brief=brief,
                transition_feedback=transition_feedback,
            )
        changed_result = json.loads(json.dumps(reviewer_result))
        changed_result["raw"]["contract_ledger"]["hard_constraints"][0][
            "claim"
        ] = "a different hard constraint"
        with self.assertRaisesRegex(ValueError, "immutable TeamRun payload"):
            require_preflight_binding(
                proposal=proposal,
                preflight_evidence=evidence,
                reviewer_result=changed_result,
            )
        invalid_schema_result = json.loads(json.dumps(reviewer_result))
        invalid_schema_result["raw"]["contract_ledger"]["hard_constraints"] = [
            {
                "assertion": "the public transform signature remains stable",
                "authority": "public_signature",
                "repair_implication": "preserve the callable",
            }
        ]
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "items require exactly"):
                record_preflight_evidence(
                    plan=plan,
                    seal=seal,
                    context_view=view,
                    review_profile=profile,
                    reviewer_result=invalid_schema_result,
                )
        collision_result = json.loads(json.dumps(reviewer_result))
        collision_result["raw"]["acceptance_plan"]["requirements"][1][
            "requirement_id"
        ] = "public-boundaries"
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "invalid or duplicate id"):
                record_preflight_evidence(
                    plan=plan,
                    seal=seal,
                    context_view=view,
                    review_profile=profile,
                    reviewer_result=collision_result,
                )
        invalid_mapping_result = json.loads(json.dumps(reviewer_result))
        invalid_mapping_result["raw"]["acceptance_plan"][
            "adapter_replay_mapping"
        ][0]["requirement_id"] = "an-unknown-requirement"
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "differs from canonical"):
                record_preflight_evidence(
                    plan=plan,
                    seal=seal,
                    context_view=view,
                    review_profile=profile,
                    reviewer_result=invalid_mapping_result,
                )
        tampered = dict(evidence)
        tampered["recommendations"] = ["different advice"]
        with self.assertRaisesRegex(ValueError, "not bound"):
            require_preflight_binding(proposal=proposal, preflight_evidence=tampered)
        forged_result = dict(reviewer_result)
        forged_result["producer"] = {"agent_id": "lead-solver", "role": "solver"}
        with self.assertRaisesRegex(ValueError, "producer differs"):
            require_preflight_binding(
                proposal=proposal,
                preflight_evidence=evidence,
                reviewer_result=forged_result,
            )

    def test_quarantined_ordered_transformation_review_is_not_exposed(self) -> None:
        self._state("contract_audit", "contract-entry")
        with patch.dict("os.environ", self.env, clear=False):
            seal = seal_contract(artifact_root=self.app, contract_sources=[self.task])
        catalog = _read_yaml(REPO / "examples/reviewer-practice-router-v1.yaml")
        with patch.dict("os.environ", self.env, clear=False):
            parsing = record_review_profile(
                draft={
                    "primary": "parsing-transformation",
                    "secondary": [],
                    "evidence": ["the public output composes named transformation stages"],
                },
                catalog=catalog,
                catalog_root=REPO / "examples",
                seal=seal,
            )
            numerical = record_review_profile(
                draft={
                    "primary": "numerical-statistical",
                    "secondary": [],
                    "evidence": ["the public output is a numerical estimate"],
                },
                catalog=catalog,
                catalog_root=REPO / "examples",
                seal=seal,
            )

        parsing_document = next(
            item
            for item in parsing["documents"]
            if item["profile_id"] == "parsing-transformation"
        )
        numerical_document = next(
            item
            for item in numerical["documents"]
            if item["profile_id"] == "numerical-statistical"
        )
        self.assertNotIn(
            "ordered_transformation_composition", parsing_document["checks"]
        )
        self.assertNotIn(
            "ordered_transformation_composition", parsing_document["content"]
        )
        self.assertNotIn(
            "ordered_transformation_composition", numerical_document["checks"]
        )

    def test_review_pre_submit_repairs_only_mechanical_fields(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        review_practices = {
            "version": 1,
            "role": "falsifier",
            "stages": [
                {"id": "bind_scope", "objective": "bind the reviewed inputs"}
            ],
            "practices": [
                {
                    "id": "public_consumer_first",
                    "allow_not_applicable": False,
                    "trigger": "Always.",
                    "procedure": "Use the strongest public consumer.",
                    "required_evidence": "Name the public surface.",
                }
            ],
        }
        for field in (
            "candidate_artifact_identity",
            "contract_seal_sha256",
            "context_view_sha256",
        ):
            del falsifier["raw"][field]
        falsifier["raw"]["review_stages"] = [
            {"id": "bind_scope", "status": "completed", "evidence": "bound"}
        ]
        falsifier["raw"]["practice_receipts"] = [
            {
                "practice_id": "public_consumer_first",
                "status": "applied",
                "evidence": "the public transform callable was replayed",
            }
        ]
        with patch.dict("os.environ", self.env, clear=False):
            receipt = canonicalize_falsifier_result(
                falsifier=falsifier,
                proposal=proposal,
                seal=seal,
                context_view=view,
                review_practices=review_practices,
            )
        canonical = receipt["result"]
        self.assertFalse(receipt["semantic_fields_modified"])
        self.assertEqual(
            canonical["raw"]["candidate_artifact_identity"],
            proposal["candidate_artifact_identity"],
        )
        self.assertEqual(
            canonical["raw"]["review_stages"][0],
            {"stage_id": "bind_scope", "status": "completed", "evidence": "bound"},
        )
        self.assertEqual(canonical["raw"]["practice_receipts"][0]["reason"], "")
        self.assertIn(
            "practice_receipts[0]:missing_reason->empty", receipt["repairs"]
        )
        decision = self._decide(seal, proposal, view, receipt)
        self.assertEqual(decision["decision"], "promote")

        conflicting = self._falsifier(seal, proposal, view)
        conflicting["raw"]["review_stages"] = [
            {
                "id": "bind_scope",
                "stage_id": "issue_verdict",
                "status": "completed",
                "evidence": "ambiguous",
            }
        ]
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "conflicting id and stage_id"):
                canonicalize_falsifier_result(
                    falsifier=conflicting,
                    proposal=proposal,
                    seal=seal,
                    context_view=view,
                )

        wrong_identity = self._falsifier(seal, proposal, view)
        wrong_identity["raw"]["candidate_artifact_identity"] = "tree-sha256:wrong"
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "conflicts with gate authority"):
                canonicalize_falsifier_result(
                    falsifier=wrong_identity,
                    proposal=proposal,
                    seal=seal,
                    context_view=view,
                )

    def _decide(
        self,
        seal: dict[str, object],
        proposal: dict[str, object],
        view: dict[str, object],
        falsifier: dict[str, object],
    ) -> dict[str, object]:
        with patch.dict("os.environ", self.env, clear=False):
            return decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=falsifier,
                artifact_root=self.app,
            )

    def test_independent_complete_falsifier_authorizes_promotion(self) -> None:
        seal, proposal, view = self._receipts()
        decision = self._decide(seal, proposal, view, self._falsifier(seal, proposal, view))
        self.assertEqual(decision["decision"], "promote")
        self.assertFalse(decision["candidate_revision_required"])
        self.assertTrue(all(decision["checks"].values()))
        with patch.dict("os.environ", self.env, clear=False):
            applied = verify_application(
                decision=decision,
                seal=seal,
                artifact_root=self.app,
                mode="promote",
            )
        self.assertTrue(applied["verified"])
        self.assertEqual(applied["artifact_provider"], "external")

    def test_deadline_degraded_quarantine_is_effective_authorization(self) -> None:
        self._state("quarantine", "quarantine-entry")
        candidate_identity = artifact_identity(self.app)
        seal = {
            "version": 1,
            "kind": "contract_seal",
            "baseline_artifact_identity": candidate_identity,
        }
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "revise",
            "candidate_artifact_identity": candidate_identity,
        }
        route = {
            "version": 1,
            "kind": "recovering_develop_review_route",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "route": "quarantine",
            "promotion_decision": "revise",
            "promotion_decision_sha256": stable_sha256(decision),
            "review_budget_exhausted": False,
            "repairable_rejection": False,
            "revision_reserve_seconds": 1500,
            "deadline_remaining_seconds": 681,
            "revision_deadline_feasible": False,
            "revision_deadline_reason": "insufficient_complete_revision_reserve",
            "deadline_budget_degraded": True,
            "artifact_disposition": "candidate_quarantined",
            "evaluation_target": "candidate",
        }
        with patch.dict("os.environ", self.env, clear=False):
            applied = verify_application(
                decision=decision,
                seal=seal,
                artifact_root=self.app,
                mode="quarantine",
                review_route=route,
            )
        self.assertTrue(applied["verified"])
        self.assertEqual(
            applied["effective_authorization_kind"],
            "recovering_develop_review_route",
        )

    def test_deadline_degraded_quarantine_requires_a_real_reserve_shortfall(self) -> None:
        self._state("quarantine", "quarantine-entry")
        candidate_identity = artifact_identity(self.app)
        seal = {
            "version": 1,
            "kind": "contract_seal",
            "baseline_artifact_identity": candidate_identity,
        }
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "revise",
            "candidate_artifact_identity": candidate_identity,
        }
        route = {
            "version": 1,
            "kind": "recovering_develop_review_route",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "route": "quarantine",
            "promotion_decision": "revise",
            "promotion_decision_sha256": stable_sha256(decision),
            "review_budget_exhausted": False,
            "repairable_rejection": False,
            "revision_reserve_seconds": 1500,
            "deadline_remaining_seconds": 1500,
            "revision_deadline_feasible": False,
            "revision_deadline_reason": "insufficient_complete_revision_reserve",
            "deadline_budget_degraded": True,
            "artifact_disposition": "candidate_quarantined",
            "evaluation_target": "candidate",
        }
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(
                ValueError,
                "bound deadline-degraded quarantine",
            ):
                verify_application(
                    decision=decision,
                    seal=seal,
                    artifact_root=self.app,
                    mode="quarantine",
                    review_route=route,
                )

    def test_candidate_blind_obligations_require_mode_compatible_closure(self) -> None:
        seal, proposal, view = self._receipts()
        preflight = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": "solve-entry",
            "producer": {"agent_id": "preflight-1", "role": "preflight-reviewer"},
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "public-boundaries",
                        "evidence_mode": "adapter_replay",
                    },
                    {
                        "requirement_id": "signature-preservation",
                        "evidence_mode": "paired_review",
                    },
                    {
                        "requirement_id": "formula-semantics",
                        "evidence_mode": "analytic_review",
                    },
                ]
            },
        }
        proposal["preflight_evidence_sha256"] = stable_sha256(preflight)
        falsifier = self._falsifier(seal, proposal, view)
        falsifier["raw"]["acceptance_obligation_assessments"] = [
            {
                "requirement_id": "public-boundaries",
                "evidence_mode": "adapter_replay",
                "status": "satisfied",
                "evidence_provenance": "adapter_replay_receipt",
                "evidence": "the bound adapter replay covered all declared strata",
                "independence_basis": "adapter-owned candidate snapshot execution",
                "unresolved_reason": "",
            },
            {
                "requirement_id": "signature-preservation",
                "evidence_mode": "paired_review",
                "status": "satisfied",
                "evidence_provenance": "paired_artifact_evidence",
                "evidence": "baseline and candidate expose the same public signature",
                "independence_basis": "reviewer inspected both immutable artifacts",
                "unresolved_reason": "",
            },
            {
                "requirement_id": "formula-semantics",
                "evidence_mode": "analytic_review",
                "status": "satisfied",
                "evidence_provenance": "independent_analytic_derivation",
                "evidence": "reviewer-derived boundary arithmetic matches the candidate",
                "independence_basis": "derived from bounded public inputs",
                "unresolved_reason": "",
            },
        ]
        with patch.dict("os.environ", self.env, clear=False):
            task = falsifier_task(
                proposal=proposal,
                seal=seal,
                context_view=view,
                preflight_evidence=preflight,
            )
            promoted = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=falsifier,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )

        assignment = task["tasks"][0]
        self.assertEqual(assignment["acceptance_plan"], preflight["acceptance_plan"])
        self.assertEqual(
            assignment["acceptance_obligation_assessment_schema"][
                "required_provenance_by_mode"
            ]["analytic_review"],
            "independent_analytic_derivation",
        )
        self.assertEqual(
            assignment["acceptance_obligation_assessment_schema"][
                "max_text_chars"
            ],
            600,
        )
        self.assertEqual(promoted["decision"], "promote")
        self.assertTrue(
            promoted["checks"]["acceptance_obligation_assessments_valid"]
        )
        self.assertTrue(
            promoted["checks"]["all_acceptance_obligations_satisfied"]
        )

        unresolved = json.loads(json.dumps(falsifier))
        unresolved_item = unresolved["raw"]["acceptance_obligation_assessments"][2]
        unresolved_item.update(
            {
                "status": "unresolved",
                "evidence_provenance": "insufficient",
                "independence_basis": "",
                "unresolved_reason": "the public population does not distinguish variants",
            }
        )
        with patch.dict("os.environ", self.env, clear=False):
            decision = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=unresolved,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(decision["decision"], "revise")
        self.assertTrue(decision["candidate_revision_required"])
        self.assertIn(
            "acceptance_obligations_unresolved_or_falsified",
            decision["reason_codes"],
        )

        wrong_provenance = json.loads(json.dumps(falsifier))
        wrong_provenance["raw"]["acceptance_obligation_assessments"][1][
            "evidence_provenance"
        ] = "independent_analytic_derivation"
        with patch.dict("os.environ", self.env, clear=False):
            decision = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=wrong_provenance,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(decision["decision"], "revise")
        self.assertIn(
            "reviewer_receipt_expression_invalid",
            decision["reason_codes"],
        )
        self.assertEqual(decision["failure_owner"], "reviewer_receipt_expression")
        self.assertFalse(decision["candidate_revision_required"])

        overlong_evidence = json.loads(json.dumps(falsifier))
        overlong_evidence["raw"]["acceptance_obligation_assessments"][0][
            "evidence"
        ] = "x" * 601
        with patch.dict("os.environ", self.env, clear=False):
            decision = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=overlong_evidence,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(decision["decision"], "revise")
        self.assertIn(
            "reviewer_receipt_expression_invalid",
            decision["reason_codes"],
        )

    def test_generalization_scope_requires_authority_and_region_dispositions(
        self,
    ) -> None:
        seal, proposal, view = self._receipts()
        preflight = {
            "version": 1,
            "kind": "plan_preflight_evidence",
            "run_id": self.run_id,
            "node": "solve",
            "entry_id": "solve-entry",
            "producer": {"agent_id": "preflight-1", "role": "preflight-reviewer"},
            "promotion_authority": False,
            "contract_seal_sha256": proposal["contract_seal_sha256"],
            "acceptance_plan_schema_version": 2,
            "acceptance_plan": {
                "requirements": [
                    {
                        "requirement_id": "unseen-semantics",
                        "evidence_mode": "analytic_review",
                        "claim_scope": "generalization",
                        "uncovered_regions": [
                            "unseen forms",
                            "observationally equivalent ordering forks",
                        ],
                    }
                ]
            },
        }
        proposal["preflight_evidence_sha256"] = stable_sha256(preflight)
        require_preflight_binding(
            proposal=proposal,
            preflight_evidence=preflight,
            require_generalization_evidence_scope=True,
        )
        legacy_preflight = json.loads(json.dumps(preflight))
        legacy_preflight["acceptance_plan_schema_version"] = 1
        legacy_proposal = json.loads(json.dumps(proposal))
        legacy_proposal["preflight_evidence_sha256"] = stable_sha256(
            legacy_preflight
        )
        with self.assertRaisesRegex(ValueError, "explicit bounded_acceptance"):
            require_preflight_binding(
                proposal=legacy_proposal,
                preflight_evidence=legacy_preflight,
                require_generalization_evidence_scope=True,
            )
        falsifier = self._falsifier(seal, proposal, view)
        assessment = {
            "requirement_id": "unseen-semantics",
            "evidence_mode": "analytic_review",
            "status": "satisfied",
            "evidence_provenance": "independent_analytic_derivation",
            "evidence": "public examples and bounded generated forms agree",
            "independence_basis": "reviewer inspected the bounded public population",
            "unresolved_reason": "",
            "generalization_assessment": {
                "evidence_population_roles": [
                    "public_acceptance",
                    "generated",
                ],
                "generalization_authority": "insufficient",
                "uncovered_region_dispositions": [
                    {
                        "region": "unseen forms",
                        "status": "unresolved",
                        "evidence": "no held-out labeled population is available",
                    },
                    {
                        "region": "observationally equivalent ordering forks",
                        "status": "unresolved",
                        "evidence": "all public forms give the same observation",
                    },
                ],
            },
        }
        falsifier["raw"]["acceptance_obligation_assessments"] = [assessment]

        with patch.dict("os.environ", self.env, clear=False):
            downgraded = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=falsifier,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(downgraded["decision"], "revise")
        self.assertTrue(
            downgraded["checks"]["acceptance_obligation_assessments_valid"]
        )
        self.assertFalse(
            downgraded["checks"]["all_acceptance_obligations_satisfied"]
        )
        normalized = downgraded["acceptance_obligation_assessments"][0]
        self.assertEqual(normalized["status"], "unresolved")
        self.assertEqual(normalized["evidence_provenance"], "insufficient")

        supported = json.loads(json.dumps(falsifier))
        supported_assessment = supported["raw"][
            "acceptance_obligation_assessments"
        ][0]
        supported_assessment["generalization_assessment"].update(
            {
                "evidence_population_roles": ["held_out"],
                "generalization_authority": "held_out_population",
                "uncovered_region_dispositions": [
                    {
                        "region": "unseen forms",
                        "status": "resolved",
                        "evidence": "a preselected held-out population covers them",
                    },
                    {
                        "region": "observationally equivalent ordering forks",
                        "status": "not_material",
                        "evidence": "the normative contract makes ordering irrelevant",
                    },
                ],
            }
        )
        with patch.dict("os.environ", self.env, clear=False):
            promoted = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=supported,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(promoted["decision"], "promote")

        missing_scope = json.loads(json.dumps(falsifier))
        del missing_scope["raw"]["acceptance_obligation_assessments"][0][
            "generalization_assessment"
        ]
        with patch.dict("os.environ", self.env, clear=False):
            repaired = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=missing_scope,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(repaired["decision"], "revise")
        self.assertTrue(
            repaired["checks"]["acceptance_obligation_assessments_valid"]
        )
        missing_normalized = repaired["acceptance_obligation_assessments"][0]
        self.assertEqual(missing_normalized["status"], "unresolved")
        self.assertEqual(
            len(
                missing_normalized["generalization_assessment"][
                    "uncovered_region_dispositions"
                ]
            ),
            2,
        )

        incomplete_regions = json.loads(json.dumps(supported))
        incomplete_regions["raw"]["acceptance_obligation_assessments"][0][
            "generalization_assessment"
        ]["uncovered_region_dispositions"].pop()
        with patch.dict("os.environ", self.env, clear=False):
            invalid = decide_promotion(
                seal=seal,
                proposal=proposal,
                context_view=view,
                falsifier=incomplete_regions,
                artifact_root=self.app,
                preflight_evidence=preflight,
            )
        self.assertEqual(invalid["decision"], "revise")
        self.assertIn(
            "reviewer_receipt_expression_invalid",
            invalid["reason_codes"],
        )
        self.assertFalse(invalid["candidate_revision_required"])

    def test_same_identity_cannot_falsify_its_own_candidate(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        falsifier["producer"]["agent_id"] = self.agent_id
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("independent_identity", decision["reason_codes"])

    def test_candidate_swap_after_review_is_inconclusive(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        self.module.write_text(
            self.baseline_text.replace("return value\n", "return value + 2\n"),
            encoding="utf-8",
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("candidate_fresh", decision["reason_codes"])

    def test_public_contract_drift_requests_revision(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        self.module.write_text(
            self.module.read_text(encoding="utf-8").replace(
                "Return the transformed value.",
                "Return a newly redefined value.",
            ),
            encoding="utf-8",
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("public_contract_unchanged", decision["reason_codes"])

    def test_contract_source_drift_forces_rollback(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(seal, proposal, view)
        self.task.write_text("tampered contract source\n", encoding="utf-8")
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "rollback")
        self.assertIn("contract_sources_unchanged", decision["reason_codes"])

    def test_incomplete_falsifier_is_inconclusive(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            coverage={"complete": False},
            verdict="inconclusive",
        )
        falsifier["coverage"] = {"complete": False}
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("falsifier_complete", decision["reason_codes"])

    def test_unpaired_reviewer_rejection_requests_revision(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            verdict="reject",
            contract_preserved=False,
            regressions=[],
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn(
            "falsifier_rejected_without_hard_evidence",
            decision["reason_codes"],
        )
        self.assertIn("contract_concern_structured", decision["reason_codes"])

    def test_direct_hard_contract_violation_requests_revision(self) -> None:
        seal, proposal, view = self._receipts()
        violation = {
            "claim": "candidate violates the public transform contract",
            "contract_basis": "public_consumer",
            "candidate_evidence": "candidate replay returns the wrong public value",
            "severity": "blocking",
            "repair_action": "repair the public result and replay the same consumer",
        }
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            verdict="reject",
            contract_preserved=False,
            regressions=[],
            contract_violations=[violation],
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertTrue(decision["checks"]["contract_concern_structured"])
        self.assertEqual(decision["blocking_contract_violations"], [violation])
        self.assertIn(
            "validated_blocking_contract_violation", decision["reason_codes"]
        )
        self.assertNotIn(
            "falsifier_rejected_without_hard_evidence", decision["reason_codes"]
        )

    def test_paired_blocking_regression_requests_revision(self) -> None:
        seal, proposal, view = self._receipts()
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            verdict="reject",
            contract_preserved=False,
            regressions=[
                {
                    "claim": "candidate breaks the public negative-value behavior",
                    "contract_basis": "public_consumer",
                    "baseline_evidence": "baseline public replay returns -1",
                    "candidate_evidence": "candidate public replay raises ValueError",
                    "severity": "blocking",
                }
            ],
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("validated_blocking_regression", decision["reason_codes"])

    def test_acceptance_evidence_binds_solver_checks_to_exact_candidate(self) -> None:
        _, proposal, _ = self._receipts()
        self._state("solve", "solve-entry")
        candidate_snapshot = {
            "version": 1,
            "kind": "filesystem_artifact_snapshot",
            "run_id": self.run_id,
            "entry_id": "solve-entry",
            "node": "solve",
            "producer": {"agent_id": "artifact-provider", "role": "artifact_provider"},
            "snapshot_kind": "candidate",
            "artifact_identity": proposal["candidate_artifact_identity"],
            "snapshot_identity": proposal["candidate_artifact_identity"],
            "snapshot_path": str(self.app),
            "expected_receipt_sha256": stable_sha256(proposal),
            "immutable": True,
        }
        draft = {
            "candidate_artifact_identity": proposal["candidate_artifact_identity"],
            "confidence": "supported",
            "independence_basis": "fresh public cases selected before the final replay",
            "checks": [
                {
                    "claim": "the public transformation preserves signed inputs",
                    "public_surface": "worker.transform",
                    "method": "bounded public input partition",
                    "outcome": "passed",
                    "evidence": "zero, positive, and negative partitions returned expected values",
                }
            ],
            "residual_risks": ["the bounded partition is not exhaustive"],
        }
        with patch.dict("os.environ", self.env, clear=False):
            receipt = record_acceptance_evidence(
                draft=draft,
                proposal=proposal,
                candidate_snapshot=candidate_snapshot,
            )
        self.assertEqual(receipt["kind"], "candidate_bound_acceptance_evidence")
        self.assertEqual(receipt["proposal_sha256"], stable_sha256(proposal))
        self.assertEqual(
            receipt["candidate_snapshot_sha256"], stable_sha256(candidate_snapshot)
        )
        self.assertEqual(
            receipt["attestation_scope"], "solver_recorded_public_execution"
        )

        stale = {**draft, "candidate_artifact_identity": "tree-sha256:stale"}
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "current candidate artifact identity"):
                record_acceptance_evidence(
                    draft=stale,
                    proposal=proposal,
                    candidate_snapshot=candidate_snapshot,
                )
        stale_snapshot = {
            **candidate_snapshot,
            "expected_receipt_sha256": "proposal-sha256:stale",
        }
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "current proposal"):
                record_acceptance_evidence(
                    draft=draft,
                    proposal=proposal,
                    candidate_snapshot=stale_snapshot,
                )

    def test_structured_hard_quantitative_gap_blocks_promotion(self) -> None:
        seal, proposal, view = self._receipts()
        gap = {
            "kind": "quantitative_acceptance",
            "claim": "geometric mean speedup must exceed the visible threshold",
            "contract_basis": "task_source",
            "evidence_status": "unresolved",
            "evidence_role": "exploration",
            "population_access": "observed_public",
            "population_id": "fixed-exploration-v1",
            "observed_evidence": "the adaptive population remains below threshold",
            "required_evidence": "fresh acceptance population clears the threshold with margin",
            "repair_action": "optimize the measured bottleneck and replay a fresh population",
        }
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            hard_contract_gaps=[gap],
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "revise")
        self.assertIn("validated_hard_contract_gap", decision["reason_codes"])
        self.assertIn("hard_contract_gaps_present", decision["reason_codes"])
        self.assertNotIn("no_hard_contract_gaps", decision["reason_codes"])
        self.assertEqual(decision["hard_contract_gaps"], [gap])

    def test_sealed_unavailable_population_is_recorded_without_forcing_recovery(self) -> None:
        seal, proposal, view = self._receipts()
        uncertainty = {
            "kind": "quantitative_acceptance",
            "claim": "the sealed acceptance population must clear the threshold",
            "contract_basis": "task_source",
            "evidence_status": "unresolved",
            "evidence_role": "acceptance",
            "population_access": "sealed_unavailable",
            "population_id": "sealed-benchmark-population",
            "observed_evidence": "authorized public checks pass with margin",
            "required_evidence": "benchmark-owned evaluation of the exact candidate",
            "repair_action": "preserve the candidate and report the residual uncertainty",
        }
        falsifier = self._falsifier(
            seal,
            proposal,
            view,
            hard_contract_gaps=[uncertainty],
        )
        decision = self._decide(seal, proposal, view, falsifier)
        self.assertEqual(decision["decision"], "promote")
        self.assertEqual(decision["hard_contract_gaps"], [])
        self.assertEqual(decision["sealed_acceptance_uncertainties"], [uncertainty])
        self.assertIn(
            "sealed_acceptance_uncertainty_recorded", decision["reason_codes"]
        )
        self.assertNotIn("validated_hard_contract_gap", decision["reason_codes"])

    def test_progress_file_is_not_part_of_artifact_identity(self) -> None:
        before = artifact_identity(self.app)
        (self.app / "progress.md").write_text("solver trajectory\n", encoding="utf-8")
        self.assertEqual(artifact_identity(self.app), before)

    def test_context_bundle_is_bounded_and_excludes_progress(self) -> None:
        (self.app / "progress.md").write_text("private solver trajectory\n", encoding="utf-8")
        (self.app / "weights.bin").write_bytes(b"\x00\xff")
        view = {
            "included": [{"path": str(self.app), "kind": "directory"}],
            "excluded_paths": [str(self.app / "progress.md")],
        }
        bundle = _context_bundle(view)
        labels = [entry["path"] for entry in bundle["entries"]]
        self.assertIn("worker.py", labels)
        self.assertIn("weights.bin", labels)
        self.assertNotIn("progress.md", labels)
        binary = next(entry for entry in bundle["entries"] if entry["path"] == "weights.bin")
        self.assertEqual(binary["omission"], "non_text")
        self.assertLessEqual(bundle["text_bytes"], 240_000)

    def test_context_view_binds_present_optional_evidence_and_records_absence(self) -> None:
        acceptance = self.root / "acceptance-evidence.json"
        acceptance.write_text('{"kind":"acceptance_evidence"}\n', encoding="utf-8")
        missing = self.root / "missing-evidence.json"
        self._state("falsify", "falsify-entry")
        with patch.dict("os.environ", self.env, clear=False):
            view = record_context_view(
                role="falsifier",
                included_paths=[self.task],
                optional_included_paths=[acceptance, missing],
            )
        included = {item["path"] for item in view["included"]}
        self.assertIn(str(acceptance.resolve()), included)
        self.assertNotIn(str(missing.resolve()), included)
        self.assertEqual(
            view["optional_includes"],
            [
                {"path": str(acceptance.resolve()), "present": True},
                {"path": str(missing.resolve()), "present": False},
            ],
        )
        roles = {item["path"]: item["role"] for item in view["included"]}
        self.assertEqual(roles[str(self.task.resolve())], "required")
        self.assertEqual(roles[str(acceptance.resolve())], "optional_evidence")

    def test_context_bundle_prioritizes_first_party_evidence_over_vendor_tree(self) -> None:
        vendor = self.app / "_vendor"
        vendor.mkdir()
        for index in range(5):
            (vendor / f"dependency_{index}.py").write_text(
                "x = '" + ("v" * 38_000) + "'\n",
                encoding="utf-8",
            )
        evidence = self.app / "validation_replay.py"
        evidence.write_text("print('first-party evidence')\n", encoding="utf-8")
        view = {
            "included": [{"path": str(self.app), "kind": "directory"}],
            "excluded_paths": [],
        }
        bundle = _context_bundle(view)
        labels = [entry["path"] for entry in bundle["entries"]]
        self.assertIn("validation_replay.py", labels)
        entry = next(
            item for item in bundle["entries"] if item["path"] == "validation_replay.py"
        )
        self.assertEqual(entry["content"], "print('first-party evidence')\n")

    def test_context_bundle_prioritizes_changed_pair_over_unchanged_tree(self) -> None:
        baseline = self.root / "baseline"
        candidate = self.root / "candidate"
        baseline.mkdir()
        candidate.mkdir()
        for index in range(8):
            content = "payload = '" + (str(index) * 38_000) + "'\n"
            (baseline / f"support_{index}.py").write_text(content, encoding="utf-8")
            (candidate / f"support_{index}.py").write_text(content, encoding="utf-8")
        (baseline / "worker.py").write_text(
            "VALUE = 'baseline'\n", encoding="utf-8"
        )
        (candidate / "worker.py").write_text(
            "VALUE = 'candidate'\n", encoding="utf-8"
        )
        evidence = self.root / "acceptance.json"
        evidence.write_text('{"status":"passed"}\n', encoding="utf-8")
        view = {
            "included": [
                {
                    "path": str(evidence),
                    "kind": "file",
                    "role": "optional_evidence",
                },
                {
                    "path": str(baseline),
                    "kind": "directory",
                    "role": "baseline_snapshot",
                },
                {
                    "path": str(candidate),
                    "kind": "directory",
                    "role": "candidate_snapshot",
                },
            ],
            "excluded_paths": [],
        }
        bundle = _context_bundle(view)
        workers = [
            entry for entry in bundle["entries"] if entry["path"] == "worker.py"
        ]
        self.assertEqual(len(workers), 2)
        self.assertEqual(
            {entry["context_role"] for entry in workers},
            {"baseline_snapshot", "candidate_snapshot"},
        )
        self.assertTrue(all(entry.get("content") for entry in workers))
        self.assertTrue(bundle["truncated"])
        self.assertTrue(bundle["core_coverage"]["complete"])
        self.assertEqual(
            bundle["core_coverage"]["changed_first_party_entry_count"], 2
        )
        self.assertLessEqual(bundle["text_bytes"], 240_000)

    def test_context_bundle_projects_large_contract_seal(self) -> None:
        seal = self.root / "contract-seal.json"
        seal.write_text(
            json.dumps(
                {
                    "version": 1,
                    "kind": "contract_seal",
                    "contract_policy": "repair_aware",
                    "baseline_artifact_identity": "tree-sha256:baseline",
                    "public_contract_snapshot": {"large": "x" * 100_000},
                    "public_contract_snapshot_sha256": "snapshot-sha",
                }
            ),
            encoding="utf-8",
        )
        bundle = _context_bundle(
            {
                "included": [
                    {"path": str(seal), "kind": "file", "role": "required"}
                ],
                "excluded_paths": [],
            }
        )
        entry = bundle["entries"][0]
        self.assertEqual(
            entry["content_projection"], "contract_seal_authority_summary"
        )
        self.assertNotIn("x" * 100, entry["content"])
        self.assertTrue(bundle["core_coverage"]["complete"])

    def test_context_bundle_marks_omitted_changed_source_as_core_incomplete(self) -> None:
        baseline = self.root / "large-baseline"
        candidate = self.root / "large-candidate"
        baseline.mkdir()
        candidate.mkdir()
        (baseline / "worker.py").write_text("a" * 90_000, encoding="utf-8")
        (candidate / "worker.py").write_text("b" * 90_000, encoding="utf-8")
        bundle = _context_bundle(
            {
                "included": [
                    {
                        "path": str(baseline),
                        "kind": "directory",
                        "role": "baseline_snapshot",
                    },
                    {
                        "path": str(candidate),
                        "kind": "directory",
                        "role": "candidate_snapshot",
                    },
                ],
                "excluded_paths": [],
            }
        )
        self.assertFalse(bundle["core_coverage"]["complete"])
        self.assertEqual(bundle["core_coverage"]["omitted_required_count"], 2)


class MultiRoleWorkerProfileTest(unittest.TestCase):
    def test_gate_catalog_loads_without_pyyaml_site_packages(self) -> None:
        script = (
            "from pathlib import Path; "
            "from integrations.harbor.experimental.multirole_promotion_gate "
            "import _read_yaml; "
            "payload=_read_yaml(Path('examples/reviewer-practice-router-v1.yaml')); "
            "assert payload['version'] == 1 and payload['profiles']"
        )
        completed = subprocess.run(
            [sys.executable, "-S", "-c", script],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_read_only_profile_uses_ephemeral_schema_output(self) -> None:
        args = Namespace(
            codex_command="codex",
            execution_profile="read-only-review",
            no_bypass=False,
            no_unified_exec=False,
            model="gpt-test",
            reasoning_effort="max",
            extra_codex_arg=[],
            cwd=str(REPO),
            prompt_file=None,
            result_file=None,
            assignment_file=None,
            task_id=None,
            agent_id="falsifier-1",
            agent_role="falsifier",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            schema = Path(temp_dir) / "schema.json"
            output = Path(temp_dir) / "output.json"
            with patch(
                "integrations.teamrun.teamrun_codex_worker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "{}", ""),
            ) as run:
                _run_codex(
                    args,
                    "review",
                    schema_file=schema,
                    output_file=output,
                )
        argv = run.call_args.args[0]
        self.assertIn("read-only", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertNotIn("--output-schema", argv)
        self.assertIn("--output-last-message", argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertEqual(argv[-2:], ["--", "-"])
        self.assertEqual(run.call_args.kwargs["input"], "review")

    def test_read_only_instruction_forbids_artifact_writes(self) -> None:
        prompt = _build_instruction(
            prompt="Try to falsify the candidate.",
            result_file=Path("/tmp/result.json"),
            assignment_file=Path("/tmp/assignment.json"),
            task_id="falsify",
            agent_id="reviewer-1",
            agent_role="falsifier",
            report_file=Path("/tmp/report.json"),
            work_dir=Path("/tmp/work"),
            execution_profile="read-only-review",
        )
        self.assertIn("execution sandbox is read-only", prompt)
        self.assertIn("agent_role: falsifier", prompt)
        self.assertNotIn("Write your TeamRun result JSON to", prompt)

    def test_adapter_selects_solver_identity_and_minimal_files(self) -> None:
        agent = MultiRoleDevelopExperimentalStatemCodex.__new__(
            MultiRoleDevelopExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._reviewer_model = "gpt-5.6-sol"
        agent._reviewer_reasoning_effort = "max"
        agent._reviewer_timeout_seconds = 240
        agent._runbook_path = (
            REPO / "examples/frontier-bench-agent-multirole-develop-exp.yaml"
        )
        env = agent._statem_env("run-1")
        self.assertEqual(env["STATEM_AGENT_ROLE"], "solver")
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("artifact_identity.py", names)
        self.assertIn("multirole_promotion_gate.py", names)
        runbook = agent._runbook_path.read_text(encoding="utf-8").lower()
        self.assertIn("read-only-review", runbook)
        self.assertNotIn("embedding-drift-monitor", runbook)

    def test_evidence_adapter_includes_bounded_acceptance_replay(self) -> None:
        agent = EvidenceDevelopV4ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        agent._runbook_path = (
            REPO / "examples/frontier-bench-agent-evidence-develop-v4-exp.yaml"
        )
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("candidate_acceptance_replay.py", names)
        self.assertIn("develop_activation_gate.py", names)
        runbook = agent._runbook_path.read_text(encoding="utf-8")
        self.assertIn("acceptance-replay-plan-draft.json", runbook)
        self.assertIn("candidate_acceptance_replay.py", runbook)
        self.assertIn("acceptance-replay.json", runbook)
        self.assertIn("--require-information-gain", runbook)
        self.assertIn("--mode shadow", runbook)


if __name__ == "__main__":
    unittest.main()
