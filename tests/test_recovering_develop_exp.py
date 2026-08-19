from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml

from integrations.harbor.experimental.artifact_identity import artifact_identity, stable_sha256
from integrations.harbor.experimental.filesystem_artifact_provider import (
    apply_snapshot,
    export_provider_bundle,
    snapshot_artifact,
)
from integrations.harbor.experimental.multirole_promotion_gate import (
    _public_contract_preserved,
    _review_protocol,
    _review_profile_receipt_state,
    _review_receipt_state,
    record_review_profile,
    verify_application,
)
from integrations.harbor.experimental.recovering_develop_guard import (
    close_cycle,
    open_cycle,
    open_review,
    require_action,
    require_review_route,
    route_review,
)
from integrations.harbor.statem_codex_multirole_develop_exp import (
    EvidenceDevelopV4ExperimentalStatemCodex,
    RecoveringMultiRoleDevelopExperimentalStatemCodex,
)
from integrations.harbor.statem_codex import TeamRunStatemCodex
from statem.core import validate_spec


REPO = Path(__file__).resolve().parents[1]
RUNBOOK = REPO / "examples/frontier-bench-agent-recovering-multirole-develop-exp.yaml"
V4_RUNBOOK = REPO / "examples/frontier-bench-agent-evidence-develop-v4-exp.yaml"


class RecoveringDevelopGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "worker.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        self.state_dir = self.root / "state"
        self.run_id = "recovering-test"
        self.ledger = self.root / "cycle-ledger.json"
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

    def _seal(self, entry_id: str) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "contract_seal",
            "run_id": self.run_id,
            "node": "contract_audit",
            "entry_id": entry_id,
            "baseline_artifact_identity": artifact_identity(self.app),
        }

    def _application(self, entry_id: str) -> dict[str, object]:
        identity = artifact_identity(self.app)
        return {
            "version": 1,
            "kind": "artifact_application_verification",
            "run_id": self.run_id,
            "node": "promote",
            "entry_id": entry_id,
            "observed_artifact_identity": identity,
            "verified": True,
        }

    def test_recoverable_failure_allows_one_bounded_retry(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            opened = open_cycle(ledger_path=self.ledger, seal=self._seal("contract-1"), max_cycles=2)
        self.assertEqual(opened["cycle"], 1)

        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft={
                    "status": "recoverable_failure",
                    "evidence": ["public replay exposed a boundary mismatch"],
                    "residual_risk": [],
                    "next_gap": "repair the boundary convention",
                },
                application=self._application("promote-1"),
                artifact_root=self.app,
            )
        self.assertEqual(decision["action"], "retry")
        require_action(decision, {"retry"})

        self._state("contract_audit", "contract-2")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(ledger_path=self.ledger, seal=self._seal("contract-2"), max_cycles=2)
        self._state("final_replay", "replay-2")
        with patch.dict("os.environ", self.env, clear=False):
            exhausted = close_cycle(
                ledger_path=self.ledger,
                replay_draft={
                    "status": "recoverable_failure",
                    "evidence": ["the mismatch remains after the second candidate"],
                    "residual_risk": [],
                    "next_gap": "an unresolved alternate interpretation remains",
                },
                application=self._application("promote-2"),
                artifact_root=self.app,
            )
        self.assertEqual(exhausted["action"], "handoff")
        require_action(exhausted, {"handoff"})

    def test_application_identity_must_still_be_live(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(ledger_path=self.ledger, seal=self._seal("contract-1"), max_cycles=2)
        application = self._application("promote-1")
        (self.app / "worker.py").write_text("def work():\n    return 2\n", encoding="utf-8")
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "changed after application"):
                close_cycle(
                    ledger_path=self.ledger,
                    replay_draft={
                        "status": "passed",
                        "evidence": ["current public replay passed"],
                        "residual_risk": [],
                        "next_gap": "",
                    },
                    application=application,
                    artifact_root=self.app,
                )

    def test_cycle_close_is_idempotent_for_the_same_entry_and_evidence(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(ledger_path=self.ledger, seal=self._seal("contract-1"), max_cycles=2)

        replay_draft = {
            "status": "recoverable_failure",
            "evidence": ["public replay exposed a boundary mismatch"],
            "residual_risk": [],
            "next_gap": "repair the boundary convention",
        }
        application = {**self._application("promote-1"), "created_at": "first"}
        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            decision = close_cycle(
                ledger_path=self.ledger,
                replay_draft=replay_draft,
                application=application,
                artifact_root=self.app,
            )
            ledger_after_close = self.ledger.read_bytes()
            replayed = close_cycle(
                ledger_path=self.ledger,
                replay_draft=replay_draft,
                application={**application, "created_at": "replayed"},
                artifact_root=self.app,
            )

        self.assertEqual(replayed, decision)
        self.assertEqual(self.ledger.read_bytes(), ledger_after_close)

        changed_draft = {**replay_draft, "next_gap": "try a different repair"}
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "different replay evidence"):
                close_cycle(
                    ledger_path=self.ledger,
                    replay_draft=changed_draft,
                    application=application,
                    artifact_root=self.app,
                )

        self._state("final_replay", "replay-2")
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "different replay evidence"):
                close_cycle(
                    ledger_path=self.ledger,
                    replay_draft=replay_draft,
                    application=application,
                    artifact_root=self.app,
                )

    def test_review_budget_exhaustion_quarantines_candidate(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(
                ledger_path=self.ledger,
                seal=self._seal("contract-1"),
                max_cycles=2,
                max_reviews=2,
            )

        seal = self._seal("contract-1")
        final_decision: dict[str, object] | None = None
        final_route: dict[str, object] | None = None
        for review_number, expected in ((1, "revise"), (2, "quarantine")):
            entry = f"falsify-{review_number}"
            decision = {
                "version": 1,
                "kind": "promotion_authorization",
                "run_id": self.run_id,
                "node": "falsify",
                "entry_id": entry,
                "decision": "revise",
                "candidate_artifact_identity": artifact_identity(self.app),
            }
            self._state("falsify", entry)
            with patch.dict("os.environ", self.env, clear=False):
                open_review(ledger_path=self.ledger)
                route = route_review(
                    ledger_path=self.ledger,
                    promotion_decision=decision,
                )
                ledger_after_first_route = self.ledger.read_bytes()
                replayed_route = route_review(
                    ledger_path=self.ledger,
                    promotion_decision=decision,
                )
            self.assertEqual(route["route"], expected)
            self.assertEqual(replayed_route, route)
            self.assertEqual(self.ledger.read_bytes(), ledger_after_first_route)
            self.assertEqual(route["promotion_decision_sha256"], stable_sha256(decision))
            require_review_route(route, {expected})
            conflicting_decision = {**decision, "decision": "rollback"}
            with patch.dict("os.environ", self.env, clear=False):
                with self.assertRaisesRegex(ValueError, "another promotion decision"):
                    route_review(
                        ledger_path=self.ledger,
                        promotion_decision=conflicting_decision,
                    )
            final_decision = decision
            final_route = route

        self.assertIsNotNone(final_decision)
        self.assertIsNotNone(final_route)
        self._state("quarantine", "quarantine-1")
        with patch.dict("os.environ", self.env, clear=False):
            verified = verify_application(
                decision=final_decision,
                seal=seal,
                artifact_root=self.app,
                mode="quarantine",
                review_route=final_route,
            )
        self.assertTrue(verified["verified"])
        self.assertEqual(
            verified["effective_authorization_kind"],
            "recovering_develop_review_route",
        )

        tampered = dict(final_route)
        tampered["promotion_decision_sha256"] = "0" * 64
        with patch.dict("os.environ", self.env, clear=False):
            with self.assertRaisesRegex(ValueError, "not bound"):
                verify_application(
                    decision=final_decision,
                    seal=seal,
                    artifact_root=self.app,
                    mode="quarantine",
                    review_route=tampered,
                )

    def test_unresolved_hard_gap_forces_next_cycle_until_independently_resolved(self) -> None:
        gap = {
            "kind": "quantitative_acceptance",
            "claim": "acceptance speedup must exceed the hard threshold",
            "contract_basis": "task_source",
            "evidence_status": "unresolved",
            "evidence_role": "exploration",
            "population_id": "exploration-v1",
            "observed_evidence": "adaptive measurements remain below threshold",
            "required_evidence": "fresh held-out population clears with margin",
            "repair_action": "optimize the remaining bottleneck on the next cycle",
        }
        gap_sha256 = stable_sha256(gap)

        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(
                ledger_path=self.ledger,
                seal=self._seal("contract-1"),
                max_cycles=2,
                max_reviews=1,
            )
        self._state("falsify", "falsify-1")
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "revise",
            "reason_codes": ["validated_hard_contract_gap"],
            "hard_contract_gaps": [gap],
        }
        with patch.dict("os.environ", self.env, clear=False):
            open_review(ledger_path=self.ledger)
            route = route_review(
                ledger_path=self.ledger,
                promotion_decision=decision,
            )
        self.assertEqual(route["route"], "quarantine")
        self.assertTrue(route["requires_recovery_cycle"])
        self.assertEqual(route["hard_contract_gap_sha256s"], [gap_sha256])

        self._state("final_replay", "replay-1")
        with patch.dict("os.environ", self.env, clear=False):
            retry = close_cycle(
                ledger_path=self.ledger,
                replay_draft={
                    "status": "passed",
                    "evidence": ["the bounded public correctness replay passed"],
                    "residual_risk": [],
                    "next_gap": "",
                    "hard_gap_resolutions": [],
                },
                application=self._application("quarantine-1"),
                artifact_root=self.app,
            )
        self.assertEqual(retry["reported_status"], "passed")
        self.assertEqual(retry["status"], "recoverable_failure")
        self.assertEqual(retry["action"], "retry")
        self.assertEqual(retry["unresolved_hard_gap_sha256s"], [gap_sha256])

        self._state("contract_audit", "contract-2")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(
                ledger_path=self.ledger,
                seal=self._seal("contract-2"),
                max_cycles=2,
                max_reviews=1,
            )
        self._state("falsify", "falsify-2")
        decision["entry_id"] = "falsify-2"
        with patch.dict("os.environ", self.env, clear=False):
            open_review(ledger_path=self.ledger)
            route_review(ledger_path=self.ledger, promotion_decision=decision)
        self._state("final_replay", "replay-2")
        with patch.dict("os.environ", self.env, clear=False):
            accepted = close_cycle(
                ledger_path=self.ledger,
                replay_draft={
                    "status": "passed",
                    "evidence": ["fresh acceptance replay cleared the threshold with margin"],
                    "residual_risk": [],
                    "next_gap": "",
                    "hard_gap_resolutions": [
                        {
                            "gap_sha256": gap_sha256,
                            "status": "resolved",
                            "evidence": "independent acceptance-v2 cleared the lower bound",
                        }
                    ],
                },
                application=self._application("quarantine-2"),
                artifact_root=self.app,
            )
        self.assertEqual(accepted["status"], "passed")
        self.assertEqual(accepted["action"], "handoff")
        self.assertEqual(accepted["unresolved_hard_gap_sha256s"], [])

    def test_repairable_regression_revises_before_quarantine(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(
                ledger_path=self.ledger,
                seal=self._seal("contract-1"),
                max_cycles=2,
                max_reviews=2,
            )

        for review_number, expected in ((1, "revise"), (2, "quarantine")):
            entry = f"falsify-{review_number}"
            decision = {
                "version": 1,
                "kind": "promotion_authorization",
                "run_id": self.run_id,
                "node": "falsify",
                "entry_id": entry,
                "decision": "rollback",
                "reason_codes": ["validated_blocking_regression"],
                "checks": {
                    "contract_sources_unchanged": True,
                    "public_contract_unchanged": True,
                },
            }
            self._state("falsify", entry)
            with patch.dict("os.environ", self.env, clear=False):
                open_review(ledger_path=self.ledger)
                route = route_review(
                    ledger_path=self.ledger,
                    promotion_decision=decision,
                )
            self.assertEqual(route["route"], expected)
            self.assertTrue(route["repairable_rejection"])
            self.assertEqual(
                route["review_budget_exhausted"], review_number == 2
            )

    def test_contract_source_drift_rolls_back_immediately(self) -> None:
        self._state("contract_audit", "contract-1")
        with patch.dict("os.environ", self.env, clear=False):
            open_cycle(
                ledger_path=self.ledger,
                seal=self._seal("contract-1"),
                max_cycles=2,
                max_reviews=2,
            )

        self._state("falsify", "falsify-1")
        decision = {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "node": "falsify",
            "entry_id": "falsify-1",
            "decision": "rollback",
            "reason_codes": [
                "contract_sources_unchanged",
            ],
            "checks": {
                "contract_sources_unchanged": False,
                "public_contract_unchanged": True,
            },
        }
        with patch.dict("os.environ", self.env, clear=False):
            open_review(ledger_path=self.ledger)
            route = route_review(
                ledger_path=self.ledger,
                promotion_decision=decision,
            )
        self.assertEqual(route["route"], "rollback")
        self.assertFalse(route["repairable_rejection"])
        self.assertFalse(route["review_budget_exhausted"])

    def test_review_profile_is_selected_before_candidate_work(self) -> None:
        self._state("contract_audit", "contract-1")
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        env = {
            **self.env,
            "STATEM_AGENT_ID": "lead-solver",
            "STATEM_AGENT_ROLE": "solver",
        }
        with patch.dict("os.environ", env, clear=False):
            profile = record_review_profile(
                draft={
                    "primary": "numerical-statistical",
                    "secondary": [],
                    "evidence": ["task operates on numerical estimators"],
                },
                catalog=catalog,
                catalog_root=REPO / "examples",
                seal=self._seal("contract-1"),
            )
        self.assertEqual(profile["primary"], "numerical-statistical")
        self.assertEqual(
            [item["profile_id"] for item in profile["documents"]],
            ["base", "numerical-statistical"],
        )

    def test_every_declared_reviewer_profile_is_loadable(self) -> None:
        self._state("contract_audit", "contract-1")
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        env = {
            **self.env,
            "STATEM_AGENT_ID": "lead-solver",
            "STATEM_AGENT_ROLE": "solver",
        }
        with patch.dict("os.environ", env, clear=False):
            for declared in catalog["profiles"]:
                profile = record_review_profile(
                    draft={
                        "primary": declared["id"],
                        "secondary": [],
                        "evidence": ["category loadability check"],
                    },
                    catalog=catalog,
                    catalog_root=REPO / "examples",
                    seal=self._seal("contract-1"),
                )
                self.assertEqual(profile["primary"], declared["id"])
                self.assertEqual(
                    profile["documents"][1]["profile_id"],
                    declared["id"],
                )
                for check_id in declared["checks"]:
                    self.assertIn(
                        f"`{check_id}`",
                        profile["documents"][1]["content"],
                    )

    def test_stateful_profile_requires_monotone_frontier_reachability(self) -> None:
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        profile = next(
            item for item in catalog["profiles"] if item["id"] == "stateful-systems"
        )
        self.assertIn("monotone_frontier_reachability", profile["checks"])
        content = (REPO / "examples/reviewer/stateful-systems.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("every reachable\n  intermediate frontier", content)
        self.assertIn("multiple pending transitions", content)
        self.assertIn("partial advancement", content)

    def test_performance_profile_requires_population_margin_and_consumer_replay(self) -> None:
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        profile = next(
            item for item in catalog["profiles"] if item["id"] == "performance-resources"
        )
        self.assertIn("acceptance_population_and_margin", profile["checks"])
        self.assertIn("consumer_execution_model", profile["checks"])
        self.assertIn("cache_readiness_and_first_call", profile["checks"])
        content = (REPO / "examples/reviewer/performance-resources.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("non-cherry-picked population", content)
        self.assertIn("contiguous or independently seeded", content)
        self.assertIn("at least ten acceptance fixtures", content)
        self.assertIn("changes verdict across consumer-equivalent", content)
        self.assertIn("process,\n  privilege, filesystem", content)
        self.assertIn("both incremental and bulk", content)
        self.assertIn("first consumer call after each", content)
        self.assertIn("explicit wall timeout and process-group cleanup", content)

    def test_base_review_requires_named_reference_adjudication(self) -> None:
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practices-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        practices = {item["id"]: item for item in catalog["practices"]}
        self.assertIn("named_reference_adjudication", practices)
        content = (REPO / "examples/reviewer/base.md").read_text(encoding="utf-8")
        self.assertIn("The baseline is not\nan authority", content)
        self.assertIn("moves toward the named reference", content)

    def test_reviewer_template_requires_all_stage_and_practice_receipts(self) -> None:
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practices-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        protocol = _review_protocol(catalog)
        raw = {
            "review_protocol_sha256": protocol["binding_sha256"],
            "review_stages": [
                {
                    "stage_id": item["id"],
                    "status": "completed",
                    "evidence": "checked",
                }
                for item in protocol["stages"]
            ],
            "practice_receipts": [
                {
                    "practice_id": item["id"],
                    "status": "applied",
                    "evidence": "public differential evidence",
                    "reason": "",
                }
                for item in protocol["practices"]
            ],
        }
        self.assertEqual(
            _review_receipt_state(raw, protocol),
            (True, True, True),
        )

        raw["review_protocol_sha256"] = protocol["catalog_sha256"]
        self.assertEqual(
            _review_receipt_state(raw, protocol),
            (False, True, True),
        )

        raw["review_protocol_sha256"] = protocol["binding_sha256"]
        raw["review_stages"] = [
            {
                "id": item["stage_id"],
                "status": item["status"],
                "evidence": item["evidence"],
            }
            for item in raw["review_stages"]
        ]
        self.assertEqual(
            _review_receipt_state(raw, protocol),
            (True, False, True),
        )

    def test_reviewer_protocol_exposes_an_unambiguous_binding(self) -> None:
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practices-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        protocol = _review_protocol(catalog)
        self.assertEqual(
            protocol["binding_sha256"],
            stable_sha256(
                {key: value for key, value in protocol.items() if key != "binding_sha256"}
            ),
        )
        self.assertNotEqual(protocol["binding_sha256"], protocol["catalog_sha256"])

    def test_selected_profile_requires_one_receipt_per_category_check(self) -> None:
        self._state("contract_audit", "contract-1")
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        env = {
            **self.env,
            "STATEM_AGENT_ID": "lead-solver",
            "STATEM_AGENT_ROLE": "solver",
        }
        with patch.dict("os.environ", env, clear=False):
            profile = record_review_profile(
                draft={
                    "primary": "numerical-statistical",
                    "secondary": [],
                    "evidence": ["task operates on numerical estimators"],
                },
                catalog=catalog,
                catalog_root=REPO / "examples",
                seal=self._seal("contract-1"),
            )
        receipts = [
            {
                "profile_id": document["profile_id"],
                "check_id": check_id,
                "status": "applied",
                "evidence": "bounded semantic check",
                "reason": "",
            }
            for document in profile["documents"]
            for check_id in document["checks"]
        ]
        self.assertEqual(
            _review_profile_receipt_state(
                {"profile_receipts": receipts},
                profile,
            ),
            (True, True),
        )
        self.assertEqual(
            _review_profile_receipt_state(
                {"profile_receipts": list(reversed(receipts))},
                profile,
            ),
            (False, False),
        )
        receipts[0]["status"] = "unresolved"
        receipts[0]["evidence"] = ""
        self.assertEqual(
            _review_profile_receipt_state(
                {"profile_receipts": receipts},
                profile,
            ),
            (True, False),
        )


class FilesystemArtifactProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.state_dir = self.root / "state"
        self.provider = self.root / "provider"
        self.run_id = "provider-test"
        state_path = self.state_dir / "runs" / self.run_id / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_snapshot_restore_is_exact_and_receipted(self) -> None:
        target = self.app / "worker.py"
        target.write_text("def work():\n    return 1\n", encoding="utf-8")
        preserved = self.app / "preserved.txt"
        preserved.write_text("baseline\n", encoding="utf-8")
        link = self.app / "current.txt"
        link.symlink_to("preserved.txt")
        baseline_identity = artifact_identity(self.app)
        with patch.dict("os.environ", self.env, clear=False):
            baseline = snapshot_artifact(
                artifact_root=self.app,
                provider_root=self.provider,
                kind="baseline",
            )
        target.write_text("def work():\n    return 2\n", encoding="utf-8")
        preserved.unlink()
        link.unlink()
        link.symlink_to("worker.py")
        extra_dir = self.app / "generated"
        extra_dir.mkdir()
        (extra_dir / "candidate.txt").write_text("remove me\n", encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            applied = apply_snapshot(
                artifact_root=self.app,
                snapshot=baseline,
                mode="restore",
            )
        self.assertEqual(artifact_identity(self.app), baseline_identity)
        self.assertEqual(applied["operation"], "transactional_restore")
        self.assertTrue(applied["verified"])
        self.assertTrue(baseline["immutable"])
        self.assertTrue(target.stat().st_mode & 0o200)
        self.assertEqual(preserved.read_text(encoding="utf-8"), "baseline\n")
        self.assertEqual(link.readlink(), Path("preserved.txt"))
        self.assertFalse(extra_dir.exists())
        self.assertEqual(
            stable_sha256(baseline),
            stable_sha256(dict(baseline)),
        )

    def test_restore_does_not_touch_unchanged_unwritable_subtree(self) -> None:
        target = self.app / "worker.py"
        target.write_text("def work():\n    return 1\n", encoding="utf-8")
        locked = self.app / "data"
        locked.mkdir()
        locked_file = locked / "immutable.txt"
        locked_file.write_text("unchanged\n", encoding="utf-8")
        locked_file.chmod(0o444)
        locked.chmod(0o555)
        baseline_identity = artifact_identity(self.app)
        try:
            with patch.dict("os.environ", self.env, clear=False):
                baseline = snapshot_artifact(
                    artifact_root=self.app,
                    provider_root=self.provider,
                    kind="baseline",
                )
            target.write_text("def work():\n    return 2\n", encoding="utf-8")
            with patch.dict("os.environ", self.env, clear=False):
                applied = apply_snapshot(
                    artifact_root=self.app,
                    snapshot=baseline,
                    mode="restore",
                )
        finally:
            locked.chmod(0o755)
            locked_file.chmod(0o644)

        self.assertEqual(artifact_identity(self.app), baseline_identity)
        self.assertEqual(target.read_text(encoding="utf-8"), "def work():\n    return 1\n")
        self.assertEqual(locked_file.read_text(encoding="utf-8"), "unchanged\n")
        self.assertEqual(applied["operation"], "transactional_restore")

    def test_quarantine_selects_reviewed_candidate_without_promotion(self) -> None:
        target = self.app / "worker.py"
        target.write_text("def work():\n    return 1\n", encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            candidate = snapshot_artifact(
                artifact_root=self.app,
                provider_root=self.provider,
                kind="candidate",
            )
        target.write_text("def work():\n    return 2\n", encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            applied = apply_snapshot(
                artifact_root=self.app,
                snapshot=candidate,
                mode="quarantine",
            )
        self.assertEqual(artifact_identity(self.app), candidate["artifact_identity"])
        self.assertEqual(applied["mode"], "quarantine")
        self.assertEqual(applied["operation"], "transactional_candidate_selection")

    def test_provider_export_preserves_snapshot_identity_with_writable_directories(self) -> None:
        target = self.app / "worker.py"
        target.write_text("def work():\n    return 1\n", encoding="utf-8")
        with patch.dict("os.environ", self.env, clear=False):
            baseline = snapshot_artifact(
                artifact_root=self.app,
                provider_root=self.provider / "snapshots",
                kind="baseline",
            )
        (self.provider / "baseline-snapshot.json").write_text(
            json.dumps(baseline), encoding="utf-8"
        )
        exported = self.root / "exported-provider"
        receipt = export_provider_bundle(
            provider_root=self.provider,
            destination=exported,
        )
        relative = Path(baseline["snapshot_path"]).relative_to(self.provider.resolve())
        exported_snapshot = exported / relative
        self.assertEqual(
            artifact_identity(exported_snapshot), baseline["snapshot_identity"]
        )
        self.assertTrue(exported_snapshot.stat().st_mode & 0o200)
        self.assertGreater(receipt["regular_file_count"], 0)
        self.assertEqual(len(receipt["verified_snapshots"]), 1)

    def test_repair_aware_contract_keeps_signatures_but_not_buggy_docs(self) -> None:
        sealed = {
            "worker.py::work": {
                "signature": "def work(value)",
                "docstring": "Return the biased estimate.",
            },
            "worker.py::module": {
                "signature": "module",
                "docstring": "Broken production behavior.",
            },
        }
        corrected_docs = {
            "worker.py::work": {
                "signature": "def work(value)",
                "docstring": "Return the unbiased estimate.",
            }
        }
        self.assertTrue(
            _public_contract_preserved(
                sealed,
                corrected_docs,
                policy="repair_aware",
            )
        )
        self.assertFalse(
            _public_contract_preserved(
                sealed,
                corrected_docs,
                policy="strict_docs",
            )
        )
        changed_signature = {
            "worker.py::work": {
                "signature": "def work(value, mode)",
                "docstring": "Return the unbiased estimate.",
            }
        }
        self.assertFalse(
            _public_contract_preserved(
                sealed,
                changed_signature,
                policy="repair_aware",
            )
        )


class RecoveringDevelopRunbookTest(unittest.TestCase):
    def test_runbook_uses_new_core_controls(self) -> None:
        payload = validate_spec(str(RUNBOOK))
        self.assertTrue(payload["ok"])
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("multi_agent:", text)
        self.assertIn("state_hooks:", text)
        self.assertIn("recovering_develop_guard.py", text)
        self.assertIn("paired baseline/candidate evidence", text)
        self.assertNotIn("embedding-drift-monitor", text)

    def test_adapter_installs_recovery_guard(self) -> None:
        agent = RecoveringMultiRoleDevelopExperimentalStatemCodex.__new__(
            RecoveringMultiRoleDevelopExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("artifact_identity.py", names)
        self.assertIn("multirole_promotion_gate.py", names)
        self.assertIn("recovering_develop_guard.py", names)
        self.assertIn("statem_stop_hook.py", names)
        self.assertEqual(
            agent._REMOTE_RECOVERY_RECEIPTS.as_posix(),
            "/tmp/statem-verification-checks/recovering-develop",
        )

    def test_v4_runbook_has_provider_revision_and_stop_hooks(self) -> None:
        payload = validate_spec(str(V4_RUNBOOK))
        self.assertTrue(payload["ok"])
        text = V4_RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("filesystem_artifact_provider.py", text)
        self.assertIn("protected_behavior_basis", text)
        self.assertIn("to: revise", text)
        self.assertIn("to: quarantine", text)
        self.assertIn("require-review --allow quarantine", text)
        self.assertIn("require-review --allow rollback", text)
        self.assertIn("preflight_reviewer", text)
        self.assertIn("--require-completed-handle", text)
        self.assertIn("require-preflight", text)
        self.assertIn("max_parallel: 1", text)
        self.assertEqual(text.count("--detach"), 0)
        self.assertNotIn("embedding-drift-monitor", text)
        self.assertEqual(text.count("state_hooks:"), 9)

    def test_v4_adapter_installs_provider(self) -> None:
        agent = EvidenceDevelopV4ExperimentalStatemCodex.__new__(
            EvidenceDevelopV4ExperimentalStatemCodex
        )
        agent._statem_source_dir = REPO
        names = [path.name for path in agent._verification_check_paths()]
        self.assertIn("filesystem_artifact_provider.py", names)
        self.assertIn("statem_stop_hook.py", names)
        self.assertIn("reviewer-practices-v1.yaml", names)
        self.assertIn("reviewer-practice-router-v1.yaml", names)
        catalog = yaml.safe_load(
            (REPO / "examples/reviewer-practice-router-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(
            {catalog["base"], *(item["file"] for item in catalog["profiles"])}
            <= set(names)
        )
        self.assertEqual(
            agent.name(),
            "ziheng-yaxin-statem-codex-evidence-develop-v4-exp",
        )

    def test_v4_adapter_enforces_terminal_state_and_installs_runtime_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        self.assertEqual(agent._reviewer_reasoning_effort, "high")
        self.assertEqual(agent._reviewer_timeout_seconds, 900)
        self.assertEqual(agent._preflight_reviewer_reasoning_effort, "medium")
        self.assertEqual(agent._preflight_reviewer_timeout_seconds, 480)
        self.assertEqual(agent._preflight_reviewer_lease_seconds, 3600)
        self.assertTrue(agent._enforce_final_state)
        self.assertEqual(agent._max_session_resumes, 8)
        augmented = agent._augment_instruction("repair the visible task", "run-1", "solve")
        self.assertIn("--agent-role preflight-reviewer", augmented)
        self.assertIn("--reasoning-effort medium", augmented)
        self.assertIn("--lease-seconds 3600", augmented)
        self.assertIn("--detach", augmented)
        self.assertIn("--join-handle", augmented)
        self.assertIn("--dangerously-bypass-hook-trust", agent.build_cli_flags())
        hook = agent._codex_stop_hook_payload()["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertIn("STATEM_STOP_REQUIRE_STATE_HOOKS=true", hook["command"])
        self.assertIn("/tmp/statem-verification-checks/statem_stop_hook.py", hook["command"])
        self.assertEqual(agent._statem_env("run-1")["PYTHONPATH"], "/tmp/statem-src")

    def test_v4_adapter_rejects_lease_shorter_than_worker_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "leave at least 60 seconds"):
                EvidenceDevelopV4ExperimentalStatemCodex(
                    logs_dir=Path(temp_dir),
                    model_name="gpt-5.6-sol",
                    preflight_reviewer_lease_seconds=599,
                )

    def test_v4_adapter_resume_prompt_requires_executable_nonterminal_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
            )
        prompt = agent._session_resume_prompt(
            {
                "current": "rollback",
                "current_entry_id": "entry-1",
            }
        )
        self.assertIn("same session and context", prompt)
        self.assertIn("rollback", prompt)
        self.assertIn("entry-1", prompt)
        self.assertIn("explicit StateM transitions", prompt)
        self.assertIn("handoff", prompt)

    def test_v4_adapter_binds_injected_auth_json_to_file_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
                extra_env={"CODEX_AUTH_JSON_PATH": "/tmp/auth.json"},
            )

        flags = agent.build_cli_flags()
        self.assertIn("-c cli_auth_credentials_store=file", flags)
        self.assertIn("--dangerously-bypass-hook-trust", flags)

    def test_v4_adapter_leaves_api_key_auth_storage_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
                extra_env={"OPENAI_API_KEY": "test-key"},
            )

        self.assertNotIn("cli_auth_credentials_store", agent.build_cli_flags())


class StatemCodexContainerUserTest(unittest.IsolatedAsyncioTestCase):
    async def test_codex_process_inherits_statem_runtime_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            agent = EvidenceDevelopV4ExperimentalStatemCodex(
                logs_dir=Path(temp_dir),
                model_name="gpt-5.6-sol",
                extra_env={"OPENAI_API_KEY": "test-key"},
            )
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(stdout="")
        )

        await agent._run_codex_with_state_resumes(
            "repair the visible task",
            SimpleNamespace(default_user=1000),
            "run-1",
        )

        initial = next(
            call
            for call in agent.exec_as_agent.await_args_list
            if "codex exec " in call.kwargs.get("command", "")
        )
        self.assertEqual(initial.kwargs["env"]["PYTHONPATH"], "/tmp/statem-src")
        self.assertEqual(initial.kwargs["env"]["STATEM_AGENT_ROLE"], "solver")
        self.assertEqual(initial.kwargs["env"]["STATEM_RUN_ID"], "run-1")

    async def test_teamrun_codex_wrappers_source_nvm_before_launch(self) -> None:
        agent = object.__new__(TeamRunStatemCodex)
        agent.exec_as_root = AsyncMock()

        await agent._post_install_statem(SimpleNamespace())

        command = agent.exec_as_root.await_args.kwargs["command"]
        self.assertEqual(command.count('if [ -s "$NVM_DIR/nvm.sh" ]'), 2)
        self.assertLess(
            command.index('if [ -s "$NVM_DIR/nvm.sh" ]'),
            command.index("teamrun_codex_worker.py"),
        )
        self.assertLess(
            command.rindex('if [ -s "$NVM_DIR/nvm.sh" ]'),
            command.index("teamrun_codex_workers.py"),
        )

    async def test_resolves_image_default_uid_for_private_auth_file(self) -> None:
        agent = object.__new__(EvidenceDevelopV4ExperimentalStatemCodex)
        agent.exec_as_agent = AsyncMock(
            return_value=SimpleNamespace(stdout="65534\n")
        )
        environment = SimpleNamespace(default_user=None)

        user = await agent._effective_agent_user(environment)

        self.assertEqual(user, 65534)
        agent.exec_as_agent.assert_awaited_once_with(
            environment,
            command="id -u",
        )

    async def test_preserves_explicit_harbor_agent_user(self) -> None:
        agent = object.__new__(EvidenceDevelopV4ExperimentalStatemCodex)
        agent.exec_as_agent = AsyncMock()
        environment = SimpleNamespace(default_user="runner")

        user = await agent._effective_agent_user(environment)

        self.assertEqual(user, "runner")
        agent.exec_as_agent.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
