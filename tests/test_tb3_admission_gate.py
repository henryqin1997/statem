from __future__ import annotations

import unittest

from integrations.harbor.experimental.tb3_admission_gate import (
    evaluate_admission,
    stable_sha256,
)


class Tb3AdmissionGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = {
            "triage_policy": {"no_progress_limit": 2},
            "fresh_holdout_candidates": [{"task": "cheap-cpu-task"}],
        }
        self.queue_bytes = b"queue-v1\n"
        self.request = {
            "task": "cheap-cpu-task",
            "control_version": "v4p35",
            "experiment_mode": "matched_k1_triage",
            "platform_class": "aws_x86_cpu",
            "dominant_limit_prior": "statem_controllable_workflow",
            "evidence_basis": "public failure surface is workflow-owned",
            "owning_control_layer": "candidate_blind_validation",
            "hardware_feasibility": "available",
            "required_cpus": 2,
            "required_memory_mb": 4096,
            "required_gpus": 0,
            "cheapest_public_discriminator": "matched_k1_direct_vs_statem",
            "expected_api_cost_usd": 3.0,
            "expected_wall_time_seconds": 3600,
            "observable_progress_target": "close one independent obligation",
            "stop_or_park_condition": "park after two no-progress attempts",
            "hypothesis_scoped_no_progress_count": 0,
            "new_generic_hypothesis": False,
            "requested_decision": "admit",
        }

    def _evaluate(self, request=None):
        return evaluate_admission(
            queue=self.queue,
            queue_bytes=self.queue_bytes,
            request=request or self.request,
            available_cpus=8,
            available_memory_mb=16384,
            available_gpus=0,
            created_at_epoch=123,
        )

    def test_admits_complete_low_cost_workflow_case(self) -> None:
        receipt = self._evaluate()

        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["admission_decision"], "admit")
        self.assertEqual(receipt["evidence_basis"], self.request["evidence_basis"])
        self.assertEqual(
            receipt["receipt_sha256"],
            stable_sha256({key: value for key, value in receipt.items() if key != "receipt_sha256"}),
        )

    def test_rejects_hardware_and_no_progress_without_new_hypothesis(self) -> None:
        request = dict(self.request)
        request.update(
            {
                "required_cpus": 16,
                "hypothesis_scoped_no_progress_count": 2,
                "requested_decision": "reject",
            }
        )

        receipt = self._evaluate(request)

        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["admission_decision"], "reject")
        self.assertIn("hardware_requirement_unavailable", receipt["decision_reasons"])
        self.assertIn(
            "hypothesis_no_progress_limit_reached", receipt["decision_reasons"]
        )

    def test_defers_capability_case_without_new_generic_hypothesis(self) -> None:
        request = dict(self.request)
        request.update(
            {
                "dominant_limit_prior": "base_model_capability",
                "requested_decision": "defer",
            }
        )

        receipt = self._evaluate(request)

        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["admission_decision"], "defer")

    def test_mismatched_requested_decision_is_invalid(self) -> None:
        request = dict(self.request)
        request["requested_decision"] = "defer"

        receipt = self._evaluate(request)

        self.assertFalse(receipt["valid"])
        self.assertEqual(receipt["admission_decision"], "admit")

    def test_rejects_unbound_task(self) -> None:
        request = dict(self.request)
        request.update({"task": "unknown", "requested_decision": "reject"})

        receipt = self._evaluate(request)

        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["admission_decision"], "reject")


if __name__ == "__main__":
    unittest.main()
