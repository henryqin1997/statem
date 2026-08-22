from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from integrations.harbor.experimental.artifact_identity import stable_sha256
from integrations.harbor.experimental.submission_eligibility_gate import (
    decide_submission,
    main as submission_gate_main,
    require_submission,
)


class SubmissionEligibilityGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.run_id = "submission-test"
        self.candidate = "tree-sha256:candidate"
        self.baseline = "tree-sha256:baseline"

    def _promotion(self, decision: str = "promote") -> dict[str, object]:
        return {
            "version": 1,
            "kind": "promotion_authorization",
            "run_id": self.run_id,
            "decision": decision,
            "falsifier_verdict": "accept" if decision == "promote" else "inconclusive",
            "candidate_artifact_identity": self.candidate,
            "baseline_artifact_identity": self.baseline,
            "checks": {"same_run": True, "candidate_bound": True},
            "blocking_contract_violations": [],
            "blocking_regressions": [],
            "hard_contract_gaps": [],
            "acceptance_obligation_assessments": [
                {"requirement_id": "public-check", "status": "satisfied"}
            ],
            "candidate_revision_required": decision != "promote",
        }

    def _route(
        self,
        promotion: dict[str, object],
        route: str,
        *,
        budget_exhausted: bool = False,
        deadline_degraded: bool = False,
    ) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "recovering_develop_review_route",
            "run_id": self.run_id,
            "promotion_decision": promotion["decision"],
            "promotion_decision_sha256": stable_sha256(promotion),
            "route": route,
            "repairable_rejection": route in {"revise", "quarantine"},
            "review_budget_exhausted": budget_exhausted,
            "deadline_budget_degraded": deadline_degraded,
        }

    def _acceptance(self, passed: bool = True) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "candidate_acceptance_replay",
            "run_id": self.run_id,
            "candidate_artifact_identity": self.candidate,
            "execution_complete": True,
            "all_passed": passed,
            "overall_status": "passed" if passed else "failed",
        }

    def _replay(self, passed: bool = True) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "recovering_develop_replay_decision",
            "run_id": self.run_id,
            "status": "passed" if passed else "terminal_failure",
            "reported_status": "passed" if passed else "terminal_failure",
            "action": "handoff",
        }

    def _recoverable_public_pass(self) -> dict[str, object]:
        return {
            "version": 1,
            "kind": "recovering_develop_replay_decision",
            "run_id": self.run_id,
            "status": "recoverable_failure",
            "reported_status": "passed",
            "action": "handoff",
        }

    def _application(self, target: str) -> dict[str, object]:
        identity = self.candidate if target == "candidate" else self.baseline
        mode = "activate" if target == "candidate" else "restore"
        return {
            "version": 1,
            "kind": "filesystem_artifact_application",
            "run_id": self.run_id,
            "mode": mode,
            "expected_artifact_identity": identity,
            "observed_artifact_identity": identity,
            "verified": True,
        }

    def test_promoted_validated_candidate_is_eligible_for_handoff(self) -> None:
        promotion = self._promotion()
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=self._route(promotion, "promote"),
            acceptance_replay=self._acceptance(),
            replay_decision=self._replay(),
            provider_application=self._application("candidate"),
        )
        self.assertTrue(receipt["promotion_eligible"])
        self.assertTrue(receipt["candidate_submission_eligible"])
        self.assertEqual(receipt["selected_submission_target"], "candidate")
        self.assertTrue(receipt["handoff_eligible"])
        require_submission(
            receipt,
            allowed_targets={"candidate"},
            require_handoff=True,
        )

    def test_strict_quarantine_is_diagnostic_only_and_requires_restore(self) -> None:
        promotion = self._promotion("revise")
        promotion["blocking_contract_violations"] = [{"severity": "blocking"}]
        promotion["hard_contract_gaps"] = [{"claim": "public failure"}]
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(False),
            replay_decision=self._replay(False),
            provider_application={
                **self._application("candidate"),
                "mode": "quarantine",
            },
            policy="strict_review",
        )
        self.assertFalse(receipt["promotion_eligible"])
        self.assertTrue(receipt["diagnostic_replay_eligible"])
        self.assertFalse(receipt["candidate_submission_eligible"])
        self.assertEqual(receipt["selected_submission_target"], "baseline")
        self.assertTrue(receipt["fallback_required"])
        self.assertFalse(receipt["handoff_eligible"])
        self.assertIn("blocking_contract_violation", receipt["reason_codes"])
        self.assertIn("hard_contract_gap", receipt["reason_codes"])

    def test_verified_baseline_restore_closes_strict_quarantine(self) -> None:
        promotion = self._promotion("revise")
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(False),
            replay_decision=self._replay(False),
            provider_application=self._application("baseline"),
            policy="strict_review",
        )
        self.assertEqual(receipt["selected_submission_target"], "baseline")
        self.assertFalse(receipt["fallback_required"])
        self.assertTrue(receipt["submission_eligible"])
        self.assertTrue(receipt["handoff_eligible"])

    def test_require_fallback_accepts_only_unapplied_baseline_target(self) -> None:
        promotion = self._promotion("revise")
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        pending = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(False),
            replay_decision=self._replay(False),
            provider_application=self._application("candidate"),
            policy="strict_review",
        )
        require_submission(
            pending,
            allowed_targets={"baseline"},
            require_fallback=True,
        )

        restored = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(False),
            replay_decision=self._replay(False),
            provider_application=self._application("baseline"),
            policy="strict_review",
        )
        with self.assertRaisesRegex(ValueError, "does not require provider fallback"):
            require_submission(
                restored,
                allowed_targets={"baseline"},
                require_fallback=True,
            )

    def test_deadline_policy_can_submit_an_independently_validated_quarantine(self) -> None:
        promotion = self._promotion("revise")
        route = self._route(promotion, "quarantine", deadline_degraded=True)
        application = self._application("candidate")
        application["mode"] = "quarantine"
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(),
            replay_decision=self._replay(),
            provider_application=application,
            policy="deadline_best_validated",
        )
        self.assertFalse(receipt["promotion_eligible"])
        self.assertTrue(receipt["candidate_submission_eligible"])
        self.assertEqual(receipt["selected_submission_target"], "candidate")
        self.assertTrue(receipt["handoff_eligible"])

    def test_deadline_policy_keeps_unresolved_advisory_separate_from_blocker(self) -> None:
        promotion = self._promotion("revise")
        promotion["checks"]["all_acceptance_obligations_satisfied"] = False
        promotion["acceptance_obligation_assessments"] = [
            {"requirement_id": "sealed-case", "status": "unresolved"}
        ]
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        application = self._application("candidate")
        application["mode"] = "quarantine"
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(),
            replay_decision=self._recoverable_public_pass(),
            provider_application=application,
            policy="deadline_best_validated",
        )
        self.assertEqual(receipt["semantic_blocker_codes"], [])
        self.assertIn(
            "acceptance_obligation_unresolved",
            receipt["advisory_uncertainty_codes"],
        )
        self.assertFalse(receipt["final_replay_passed"])
        self.assertTrue(receipt["public_replay_passed"])
        self.assertTrue(receipt["candidate_submission_eligible"])
        self.assertTrue(receipt["handoff_eligible"])

    def test_deadline_policy_fails_closed_on_any_semantic_blocker(self) -> None:
        for field, value in (
            ("blocking_regressions", [{"severity": "blocking"}]),
            ("blocking_contract_violations", [{"severity": "blocking"}]),
            ("hard_contract_gaps", [{"claim": "observed public gap"}]),
        ):
            with self.subTest(field=field):
                promotion = self._promotion("revise")
                promotion[field] = value
                route = self._route(promotion, "quarantine", budget_exhausted=True)
                application = self._application("candidate")
                application["mode"] = "quarantine"
                receipt = decide_submission(
                    promotion_decision=promotion,
                    review_route=route,
                    acceptance_replay=self._acceptance(),
                    replay_decision=self._replay(),
                    provider_application=application,
                    policy="deadline_best_validated",
                )
                self.assertFalse(receipt["candidate_submission_eligible"])
                self.assertEqual(receipt["selected_submission_target"], "baseline")
                self.assertTrue(receipt["fallback_required"])

    def test_deadline_policy_fails_closed_on_falsified_obligation(self) -> None:
        promotion = self._promotion("revise")
        promotion["checks"]["all_acceptance_obligations_satisfied"] = False
        promotion["acceptance_obligation_assessments"] = [
            {"requirement_id": "public-case", "status": "falsified"}
        ]
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        application = self._application("candidate")
        application["mode"] = "quarantine"
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=route,
            acceptance_replay=self._acceptance(),
            replay_decision=self._recoverable_public_pass(),
            provider_application=application,
            policy="deadline_best_validated",
        )
        self.assertIn("acceptance_obligation_falsified", receipt["semantic_blocker_codes"])
        self.assertEqual(receipt["selected_submission_target"], "baseline")
        self.assertFalse(receipt["handoff_eligible"])

    def test_failed_final_replay_forces_baseline_even_after_promotion(self) -> None:
        promotion = self._promotion()
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=self._route(promotion, "promote"),
            acceptance_replay=self._acceptance(),
            replay_decision=self._replay(False),
            provider_application=self._application("candidate"),
        )
        self.assertTrue(receipt["promotion_authorized"])
        self.assertFalse(receipt["promotion_eligible"])
        self.assertFalse(receipt["candidate_submission_eligible"])
        self.assertEqual(receipt["selected_submission_target"], "baseline")
        self.assertTrue(receipt["fallback_required"])

    def test_revise_cannot_handoff_before_an_effective_terminal_route(self) -> None:
        promotion = self._promotion("revise")
        receipt = decide_submission(
            promotion_decision=promotion,
            review_route=self._route(promotion, "revise"),
            acceptance_replay=None,
            replay_decision=None,
            provider_application=None,
        )
        self.assertEqual(receipt["selected_submission_target"], "none")
        self.assertFalse(receipt["submission_eligible"])
        self.assertFalse(receipt["handoff_eligible"])

    def test_cli_reuses_an_equivalent_receipt(self) -> None:
        promotion = self._promotion()
        route = self._route(promotion, "promote")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "promotion": root / "promotion.json",
                "route": root / "route.json",
                "acceptance": root / "acceptance.json",
                "replay": root / "replay.json",
                "application": root / "application.json",
                "output": root / "output.json",
            }
            values = {
                "promotion": promotion,
                "route": route,
                "acceptance": self._acceptance(),
                "replay": self._replay(),
                "application": self._application("candidate"),
            }
            for name, value in values.items():
                paths[name].write_text(json.dumps(value), encoding="utf-8")
            argv = [
                "decide",
                "--promotion-decision",
                str(paths["promotion"]),
                "--review-route",
                str(paths["route"]),
                "--acceptance-replay",
                str(paths["acceptance"]),
                "--replay-decision",
                str(paths["replay"]),
                "--provider-application",
                str(paths["application"]),
                "--output",
                str(paths["output"]),
            ]
            with patch(
                "integrations.harbor.experimental.submission_eligibility_gate._now",
                return_value="2026-08-22T00:00:00Z",
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(submission_gate_main(argv), 0)
            first = paths["output"].read_bytes()
            with patch(
                "integrations.harbor.experimental.submission_eligibility_gate._now",
                return_value="2026-08-22T00:01:00Z",
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(submission_gate_main(argv), 0)
            self.assertEqual(paths["output"].read_bytes(), first)

    def test_review_route_must_bind_exact_promotion_receipt(self) -> None:
        promotion = self._promotion()
        route = self._route(promotion, "promote")
        route["promotion_decision_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "not bound"):
            decide_submission(
                promotion_decision=promotion,
                review_route=route,
                acceptance_replay=self._acceptance(),
                replay_decision=self._replay(),
                provider_application=self._application("candidate"),
            )

    def test_pretrain_like_blocker_cannot_reach_handoff_on_quarantined_candidate(self) -> None:
        promotion = self._promotion("revise")
        promotion["blocking_contract_violations"] = [{"severity": "blocking"}]
        promotion["hard_contract_gaps"] = [{"claim": "missing authority"}]
        promotion["candidate_revision_required"] = True
        route = self._route(promotion, "quarantine", budget_exhausted=True)
        application = self._application("candidate")
        application["mode"] = "quarantine"
        receipt = decide_submission(
            promotion_decision=copy.deepcopy(promotion),
            review_route=route,
            acceptance_replay=self._acceptance(False),
            replay_decision=self._replay(False),
            provider_application=application,
            policy="strict_review",
        )
        self.assertFalse(receipt["candidate_submission_eligible"])
        self.assertEqual(receipt["selected_submission_target"], "baseline")
        self.assertFalse(receipt["handoff_eligible"])


if __name__ == "__main__":
    unittest.main()
