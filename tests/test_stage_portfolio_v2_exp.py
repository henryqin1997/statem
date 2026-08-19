from __future__ import annotations

import unittest

from integrations.harbor.experimental.stage_portfolio_v2 import (
    authorize_stage_selection,
    record_stage_plan,
    screen_stage_candidates,
)


class StagePortfolioV2Test(unittest.TestCase):
    def _plan_draft(self) -> dict[str, object]:
        return {
            "objective": "repair the public workflow through independently checkable stages",
            "stages": [
                {
                    "stage_id": "semantic-core",
                    "objective": "select a semantically correct core repair",
                    "inputs": ["visible contract ledger", "incumbent snapshot"],
                    "outputs": ["isolated candidate snapshot"],
                    "invariants": ["public interface remains stable"],
                    "acceptance_checks": ["public-oracle", "protected-behavior"],
                    "resource_budget": {"wall_seconds": 300, "tool_calls": 20},
                    "dependencies": [],
                    "risk": "high",
                    "challenger_budget": 2,
                },
                {
                    "stage_id": "integration",
                    "objective": "integrate the selected stage artifact",
                    "inputs": ["selected semantic-core snapshot"],
                    "outputs": ["integrated candidate"],
                    "invariants": ["stage winner has no promotion authority"],
                    "acceptance_checks": ["integration-replay"],
                    "resource_budget": {"wall_seconds": 180, "tool_calls": 10},
                    "dependencies": ["semantic-core"],
                    "risk": "medium",
                    "challenger_budget": 1,
                },
            ],
        }

    def _candidate(self, candidate_id: str, oracle_status: str) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "stage_id": "semantic-core",
            "producer_id": f"worker-{candidate_id}",
            "artifact_identity": f"tree-sha256:{candidate_id}",
            "snapshot_sha256": candidate_id * 64,
            "mandatory_checks": [
                {
                    "check_id": "public-oracle",
                    "status": oracle_status,
                    "evidence": f"public oracle {oracle_status}",
                },
                {
                    "check_id": "protected-behavior",
                    "status": "passed",
                    "evidence": "paired replay preserved the invariant",
                },
            ],
            "optional_checks": [],
            "resource_usage": {"wall_seconds": 120, "tool_calls": 8},
            "isolation": "isolated_snapshot",
        }

    def test_screen_then_reviewer_rank_keeps_final_promotion_separate(self) -> None:
        plan = record_stage_plan(self._plan_draft())
        screen = screen_stage_candidates(
            plan=plan,
            stage_id="semantic-core",
            candidates=[self._candidate("a", "passed"), self._candidate("b", "failed")],
        )
        self.assertEqual(screen["eligible_candidate_ids"], ["a"])
        self.assertEqual(screen["rejected_candidates"][0]["candidate_id"], "b")
        self.assertFalse(screen["semantic_ranking_performed"])

        selection = authorize_stage_selection(
            plan=plan,
            screen=screen,
            ranking={
                "stage_id": "semantic-core",
                "plan_sha256": plan["plan_sha256"],
                "reviewer_id": "independent-stage-reviewer",
                "candidate_order": ["a"],
                "winner_id": "a",
                "evidence": ["candidate a passed every mandatory check"],
                "unresolved": False,
            },
        )
        self.assertEqual(selection["winner_id"], "a")
        self.assertTrue(selection["lead_integration_authorized"])
        self.assertFalse(selection["final_promotion_authority"])
        self.assertTrue(selection["untouched_final_replay_required"])

    def test_only_high_risk_stage_may_have_two_challengers(self) -> None:
        draft = self._plan_draft()
        draft["stages"][1]["challenger_budget"] = 2
        with self.assertRaisesRegex(ValueError, "only a high-risk stage"):
            record_stage_plan(draft)

    def test_dependencies_must_be_ordered_and_candidate_budget_is_bounded(self) -> None:
        draft = self._plan_draft()
        draft["stages"][0]["dependencies"] = ["integration"]
        with self.assertRaisesRegex(ValueError, "earlier stages"):
            record_stage_plan(draft)

        plan = record_stage_plan(self._plan_draft())
        with self.assertRaisesRegex(ValueError, "challenger budget"):
            screen_stage_candidates(
                plan=plan,
                stage_id="semantic-core",
                candidates=[
                    self._candidate("a", "passed"),
                    self._candidate("b", "passed"),
                    self._candidate("c", "passed"),
                ],
            )

    def test_reviewer_cannot_select_ineligible_or_unresolved_winner(self) -> None:
        plan = record_stage_plan(self._plan_draft())
        screen = screen_stage_candidates(
            plan=plan,
            stage_id="semantic-core",
            candidates=[self._candidate("a", "passed"), self._candidate("b", "failed")],
        )
        ranking = {
            "stage_id": "semantic-core",
            "plan_sha256": plan["plan_sha256"],
            "reviewer_id": "reviewer",
            "candidate_order": ["a"],
            "winner_id": "b",
            "evidence": ["unsupported preference"],
            "unresolved": False,
        }
        with self.assertRaisesRegex(ValueError, "winner"):
            authorize_stage_selection(plan=plan, screen=screen, ranking=ranking)

        ranking["winner_id"] = "a"
        ranking["unresolved"] = True
        with self.assertRaisesRegex(ValueError, "cannot select"):
            authorize_stage_selection(plan=plan, screen=screen, ranking=ranking)


if __name__ == "__main__":
    unittest.main()
