from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from integrations.harbor.experimental.tb3_fresh_score_gate import (
    ESTIMATE_USE,
    evaluate_score_ledger,
)


REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / ".statem/benchmarks/analysis/20260820-tb3-phase1-fresh-score-ledger.yaml"


class FreshScoreGateTest(unittest.TestCase):
    def test_current_ledger_reports_triage_without_score_estimate(self) -> None:
        ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
        receipt = evaluate_score_ledger(ledger)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["triage_pair_count"], 7)
        self.assertEqual(receipt["observed_triage_reward_delta"], 1.0)
        self.assertEqual(receipt["estimated_pair_count"], 0)
        self.assertIsNone(receipt["estimated_score_delta_pp"])
        self.assertFalse(receipt["target_supported"])

    def test_score_eligible_pair_requires_explicit_freshness(self) -> None:
        ledger = _synthetic_ledger(task_count=1, trials_per_task=5)
        ledger["pairs"][0]["fresh_for_frozen_control"] = False
        with self.assertRaisesRegex(ValueError, "fresh_for_frozen_control"):
            evaluate_score_ledger(ledger)

    def test_protocol_invalid_pair_can_only_be_excluded(self) -> None:
        ledger = _synthetic_ledger(task_count=1, trials_per_task=5)
        ledger["pairs"][0]["score_eligible"] = False
        ledger["pairs"][0]["statem"]["protocol_valid"] = False
        ledger["pairs"][0]["statem"]["raw_reward"] = None
        receipt = evaluate_score_ledger(ledger)
        self.assertEqual(receipt["estimated_pair_count"], 0)
        self.assertEqual(receipt["excluded_pair_count"], 1)
        self.assertFalse(receipt["target_supported"])

    def test_full_matched_estimate_can_support_target(self) -> None:
        ledger = _synthetic_ledger(task_count=4, trials_per_task=5)
        ledger["objective"]["target_delta"] = 15
        ledger["objective"]["target_additional_reward_over_370"] = 3.0
        for index, pair in enumerate(ledger["pairs"]):
            pair["statem"]["raw_reward"] = 1.0 if index < 3 else 0.0
        receipt = evaluate_score_ledger(ledger)
        self.assertEqual(receipt["estimated_trial_count_per_agent"], 20)
        self.assertEqual(receipt["estimated_score_delta_pp"], 15.0)
        self.assertTrue(receipt["target_supported"])

    def test_partial_estimate_never_supports_global_target(self) -> None:
        ledger = _synthetic_ledger(task_count=2, trials_per_task=5)
        ledger["objective"]["official_task_count"] = 4
        ledger["objective"]["target_additional_reward_over_370"] = 3.0
        receipt = evaluate_score_ledger(ledger)
        self.assertIsNone(receipt["estimated_score_delta_pp"])
        self.assertFalse(receipt["target_supported"])


def _synthetic_ledger(*, task_count: int, trials_per_task: int) -> dict:
    direct_agent = "codex-auth-no-session-baseline-v2"
    statem_agent = "ziheng-yaxin-statem-codex-evidence-develop-v4p41-exp"
    pair = {
        "pair_id": "pair-0",
        "task": "terminal-bench/task-0",
        "sample_count_per_agent": trials_per_task,
        "model": "gpt-5.6-sol",
        "codex_version": "0.148.0",
        "reasoning_effort": "max",
        "platform_class": "aws_x86_64_docker",
        "timeout_multiplier": 1.0,
        "environment_build_timeout_multiplier": 1.0,
        "retry_policy": "no_retries",
        "no_upload": True,
        "fresh_for_frozen_control": True,
        "frozen_control_commit": "abc1234",
        "direct": _result("direct-0", direct_agent, reward=0.0, handoff=False),
        "statem": _result("statem-0", statem_agent, reward=0.0, handoff=True),
        "score_eligible": True,
        "use": ESTIMATE_USE,
    }
    pairs = []
    for index in range(task_count):
        item = copy.deepcopy(pair)
        item["pair_id"] = f"pair-{index}"
        item["task"] = f"terminal-bench/task-{index}"
        item["direct"]["job"] = f"direct-{index}"
        item["statem"]["job"] = f"statem-{index}"
        pairs.append(item)
    return {
        "version": 2,
        "objective": {
            "metric": "terminal_bench_3_raw_percentage_points",
            "target_delta": 15,
            "official_task_count": task_count,
            "trials_per_task": trials_per_task,
            "target_additional_reward_over_370": task_count * trials_per_task * 0.15,
        },
        "eligibility_contract": {
            "allowed_direct_agents": [direct_agent],
            "allowed_statem_agents": [statem_agent],
        },
        "pairs": pairs,
    }


def _result(job: str, agent: str, *, reward: float, handoff: bool) -> dict:
    value = {
        "job": job,
        "agent": agent,
        "raw_reward": reward,
        "reward_valid": True,
        "protocol_valid": True,
        "atif_schema": "ATIF-v1.5",
        "raw_session_paths": 0,
        "backup_files": 1,
        "backup_bytes": 1,
        "backup_tree_sha256": "a" * 64,
    }
    if handoff:
        value["final_statem_state"] = "handoff"
    return value


if __name__ == "__main__":
    unittest.main()
