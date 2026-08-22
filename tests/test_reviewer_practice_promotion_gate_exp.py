from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.experimental.artifact_identity import stable_sha256
from integrations.harbor.experimental.multirole_promotion_gate import _read_yaml
from integrations.harbor.experimental.reviewer_practice_promotion_gate import (
    evaluate_candidate,
    main,
)


REPO = Path(__file__).resolve().parents[1]
POLICY = _read_yaml(REPO / "examples/reviewer-practice-promotion-v1.yaml")


class ReviewerPracticePromotionGateTest(unittest.TestCase):
    def _candidate(self) -> dict[str, object]:
        candidate: dict[str, object] = {
            "version": 1,
            "kind": "reviewer_practice_candidate",
            "practice_id": "ordered_transformation_composition",
            "trigger": "Two or more public transformations have observable order.",
            "procedure": "Bind precedence and replay stage-local and end-to-end witnesses.",
            "required_evidence": "Public authority, a distinguishing case, and exact replay.",
            "abstention_conditions": ["Only one transformation is public."],
            "known_failure_modes": ["All sampled cases collapse to the same output."],
            "development_evidence": [],
            "holdout_evidence": [],
            "sentinel_evidence": [],
        }
        mechanism = "a" * 64
        for index, family in enumerate(("structured", "algorithm"), start=1):
            candidate["development_evidence"].append(
                {
                    "task_id": f"development-{index}",
                    "task_family": family,
                    "mechanism_fingerprint": mechanism,
                    "mechanism_observed": True,
                    "reward_valid": True,
                    "protocol_valid": True,
                    "public_evidence_only": True,
                    "raw_reward": 1.0,
                    "cost_usd": 2.0,
                    "wall_seconds": 120.0,
                    "evidence_sha256": str(index) * 64,
                }
            )
        practice_sha = stable_sha256(
            {
                field: candidate[field]
                for field in (
                    "practice_id",
                    "trigger",
                    "procedure",
                    "required_evidence",
                    "abstention_conditions",
                    "known_failure_modes",
                )
            }
        )
        common = {
            "frozen_practice_sha256": practice_sha,
            "reward_before": 0.0,
            "reward_after": 1.0,
            "reward_valid": True,
            "protocol_valid": True,
            "public_evidence_only": True,
            "cost_usd_before": 1.0,
            "cost_usd_after": 2.0,
            "wall_seconds_before": 60.0,
            "wall_seconds_after": 120.0,
        }
        candidate["holdout_evidence"] = [
            {
                **common,
                "task_id": "fresh-holdout",
                "task_family": "linguistics",
                "fresh_after_freeze": True,
                "evidence_sha256": "b" * 64,
            }
        ]
        candidate["sentinel_evidence"] = [
            {
                **common,
                "task_id": "passing-sentinel",
                "task_family": "performance",
                "unchanged_sentinel": True,
                "evidence_sha256": "c" * 64,
            }
        ]
        return candidate

    def test_complete_independent_evidence_promotes(self) -> None:
        decision = evaluate_candidate(candidate=self._candidate(), policy=POLICY)
        self.assertEqual(decision["decision"], "promote")
        self.assertEqual(decision["evidence_counts"]["valid_development_tasks"], 2)
        self.assertTrue(all(decision["reporting"].values()))

    def test_one_development_family_quarantines(self) -> None:
        candidate = self._candidate()
        candidate["development_evidence"][1]["task_family"] = "structured"
        decision = evaluate_candidate(candidate=candidate, policy=POLICY)
        self.assertEqual(decision["decision"], "quarantine")
        self.assertIn(
            "insufficient distinct development task families",
            decision["quarantine_reasons"],
        )

    def test_stale_holdout_binding_quarantines(self) -> None:
        candidate = self._candidate()
        candidate["holdout_evidence"][0]["frozen_practice_sha256"] = "d" * 64
        decision = evaluate_candidate(candidate=candidate, policy=POLICY)
        self.assertEqual(decision["decision"], "quarantine")
        self.assertIn(
            "missing fresh non-regressing holdout evidence",
            decision["quarantine_reasons"],
        )

    def test_sentinel_reward_regression_quarantines(self) -> None:
        candidate = self._candidate()
        candidate["sentinel_evidence"][0]["reward_before"] = 1.0
        candidate["sentinel_evidence"][0]["reward_after"] = 0.0
        decision = evaluate_candidate(candidate=candidate, policy=POLICY)
        self.assertEqual(decision["decision"], "quarantine")
        self.assertIn(
            "missing unchanged non-regressing sentinel evidence",
            decision["quarantine_reasons"],
        )

    def test_task_identifier_in_generic_text_rejects(self) -> None:
        candidate = self._candidate()
        candidate["procedure"] = "Special-case development-1 before replay."
        decision = evaluate_candidate(candidate=candidate, policy=POLICY)
        self.assertEqual(decision["decision"], "reject")
        self.assertIn(
            "generic practice text contains a task identifier",
            decision["reject_reasons"],
        )

    def test_non_public_evidence_rejects(self) -> None:
        candidate = self._candidate()
        candidate["development_evidence"][0]["public_evidence_only"] = False
        decision = evaluate_candidate(candidate=candidate, policy=POLICY)
        self.assertEqual(decision["decision"], "reject")
        self.assertIn("candidate relies on non-public evidence", decision["reject_reasons"])

    def test_cli_writes_bound_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate_path = root / "candidate.json"
            output_path = root / "decision.json"
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self.assertEqual(
                main(
                    [
                        "--candidate",
                        str(candidate_path),
                        "--policy",
                        str(REPO / "examples/reviewer-practice-promotion-v1.yaml"),
                        "--output",
                        str(output_path),
                    ]
                ),
                0,
            )
            decision = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "promote")

    def test_quarantined_candidate_is_absent_from_runtime_practice(self) -> None:
        decision = json.loads(
            (
                REPO
                / ".statem/benchmarks/analysis/reviewer-practice-gates/ordered-transformation-v4p48.decision.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(decision["decision"], "quarantine")

        router = _read_yaml(REPO / "examples/reviewer-practice-router-v1.yaml")
        parsing_profile = next(
            profile
            for profile in router["profiles"]
            if profile["id"] == "parsing-transformation"
        )
        self.assertNotIn(
            "ordered_transformation_composition",
            parsing_profile["checks"],
        )
        practice = (
            REPO / "examples/reviewer/parsing-transformation.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ordered_transformation_composition", practice)


if __name__ == "__main__":
    unittest.main()
