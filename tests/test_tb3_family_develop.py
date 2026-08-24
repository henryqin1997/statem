from __future__ import annotations

import unittest

from integrations.harbor.experimental.tb3_family_develop import (
    authorize_next_experiment,
    build_adapted_contrast,
    record_lane_outcome,
    validate_practice_candidate,
)


def _candidate(**overrides):
    value = {
        "version": 1,
        "status": "candidate",
        "family_id": "algorithm-performance",
        "practice_id": "algorithm_performance_compact",
        "failure_owner": "validation",
        "claim_scope": "family_general",
        "changed_controls": ["algorithm_performance_compact"],
        "earliest_divergence": "acceptance population omitted cold construction",
        "hypotheses": ["cold construction owns the miss", "algorithm owns the miss"],
        "public_discriminator": "fixed cold and warm public consumer population",
        "validation_delta": "measure both construction paths with stable identity",
        "predicted_observation": "cold-path miss disappears without semantic drift",
        "decision_if_positive": "freeze the compact practice",
        "decision_if_negative": "rebranch or park",
        "protected_behavior": ["exact public semantics"],
        "compact": {
            "obligations": ["Measure the public cold and warm construction paths."],
            "stop_rule": "Stop after the fixed population is resolved.",
        },
        "detailed": {
            "reviewer_only": True,
            "prioritized_checks": ["consumer_execution_model"],
        },
        "estimated_cost_usd": 3.0,
        "deadline_feasible": True,
    }
    value.update(overrides)
    return value


class Tb3FamilyDevelopTest(unittest.TestCase):
    def test_adapted_contrast_is_never_score_evidence(self) -> None:
        common = {
            "task_family": "algorithm-performance",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "platform_class": "local-arm",
            "timeout_multiplier": 1.0,
            "retry_policy": "none",
        }
        negative = {**common, "raw_reward": 0, "active_controls": []}
        positive = {
            **common,
            "raw_reward": 1,
            "active_controls": ["algorithm_performance_compact"],
        }
        contrast = build_adapted_contrast(negative, positive)
        self.assertFalse(contrast["score_eligible"])
        self.assertEqual(contrast["causal_status"], "isolated_candidate")
        self.assertEqual(contrast["raw_delta"], 1.0)

    def test_multiple_changed_controls_require_causal_isolation(self) -> None:
        decision = authorize_next_experiment(
            _candidate(changed_controls=["primary", "supplement"])
        )
        self.assertTrue(decision["authorized"])
        self.assertEqual(decision["experiment"], "adapted_control_isolation")

    def test_transfer_choice_follows_claim_not_a_mechanical_rule(self) -> None:
        same_task = authorize_next_experiment(_candidate(claim_scope="task_boundary"))
        family = authorize_next_experiment(_candidate(claim_scope="family_general"))
        sentinel = authorize_next_experiment(
            _candidate(claim_scope="negative_transfer")
        )
        self.assertEqual(same_task["experiment"], "same_task_independent_evidence")
        self.assertEqual(family["experiment"], "untouched_same_family_transfer")
        self.assertEqual(sentinel["experiment"], "known_positive_sentinel")
        self.assertEqual(sentinel["lane"], "safety")

    def test_controller_failure_uses_fixture_instead_of_rollout(self) -> None:
        decision = authorize_next_experiment(_candidate(failure_owner="controller"))
        self.assertFalse(decision["authorized"])
        self.assertEqual(decision["next"], "focused_fixture_or_bounded_subagent")

    def test_duplicate_discriminator_is_rejected(self) -> None:
        first = authorize_next_experiment(_candidate())
        second = authorize_next_experiment(
            _candidate(),
            prior_discriminator_ids={first["discriminator_id"]},
        )
        self.assertFalse(second["authorized"])
        self.assertEqual(second["reason"], "duplicate_discriminator")

    def test_no_extractable_control_is_valid_and_parks(self) -> None:
        candidate = _candidate(status="no_extractable_control")
        self.assertEqual(validate_practice_candidate(candidate), [])
        decision = authorize_next_experiment(candidate)
        self.assertFalse(decision["authorized"])
        self.assertEqual(decision["next"], "park")

    def test_compact_and_detailed_budgets_are_bounded(self) -> None:
        errors = validate_practice_candidate(
            _candidate(
                compact={
                    "obligations": ["a", "b", "c", "d"],
                    "stop_rule": "done",
                },
                detailed={
                    "reviewer_only": True,
                    "prioritized_checks": ["a", "b", "c", "d", "e", "f"],
                },
            )
        )
        self.assertTrue(any("one to three" in error for error in errors))
        self.assertTrue(any("one to five" in error for error in errors))

    def test_lane_outcome_has_stable_identity(self) -> None:
        ledger = record_lane_outcome({}, "develop", {"raw_reward": 0})
        self.assertEqual(ledger["outcomes"][0]["lane"], "develop")
        self.assertEqual(len(ledger["outcomes"][0]["identity"]), 64)


if __name__ == "__main__":
    unittest.main()
