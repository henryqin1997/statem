from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from integrations.harbor.experimental.tb3_prelaunch_history_check import (
    build_history_index,
    build_history_receipt,
    validate_history_index,
    validate_history_receipt,
)


class Tb3PrelaunchHistoryCheckTest(unittest.TestCase):
    def _history(
        self,
        root: Path,
        *,
        reward: float | None = 1.0,
        task: str = "sample-task",
    ) -> Path:
        trial = root / "prior-job" / "trial-1"
        trial.mkdir(parents=True)
        payload = {
            "id": "trial-1",
            "task_name": task,
            "agent_info": {
                "name": "direct-agent",
                "version": "0.148.0",
                "model_info": {"name": "model-x"},
            },
            "exception_info": None if reward is not None else {"type": "error"},
            "verifier_result": (
                {"rewards": {"reward": reward}} if reward is not None else None
            ),
        }
        (trial / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        (root / "prior-job" / "result.json").write_text("{}", encoding="utf-8")
        return root

    def test_valid_direct_history_rejects_fresh_across_version_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = build_history_index([self._history(Path(temp_dir))])
        receipt = build_history_receipt(
            index=index,
            task="sample-task",
            job_name="new-job",
            agent_name="direct-agent",
            model="model-x",
            codex_version="0.149.1",
            evidence_class="fresh_direct",
        )
        self.assertEqual(receipt["decision"], "reject")
        self.assertEqual(receipt["reason"], "prior_reward_valid_direct_observation")
        self.assertFalse(receipt["score_eligible"])

    def test_new_task_is_admitted_as_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = build_history_index([self._history(Path(temp_dir))])
        receipt = build_history_receipt(
            index=index,
            task="different-task",
            job_name="new-job",
            agent_name="direct-agent",
            model="model-x",
            codex_version="0.149.1",
            evidence_class="fresh_direct",
        )
        self.assertEqual(receipt["decision"], "admit")
        self.assertTrue(receipt["score_eligible"])

    def test_replacement_requires_invalid_prior_and_changed_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = build_history_index(
                [self._history(Path(temp_dir), reward=None)]
            )
        missing = build_history_receipt(
            index=index,
            task="sample-task",
            job_name="replacement",
            agent_name="direct-agent",
            model="model-x",
            codex_version="0.149.1",
            evidence_class="infrastructure_replacement",
        )
        admitted = build_history_receipt(
            index=index,
            task="sample-task",
            job_name="replacement",
            agent_name="direct-agent",
            model="model-x",
            codex_version="0.149.1",
            evidence_class="infrastructure_replacement",
            boundary_change_reason="runtime field support changed",
        )
        self.assertEqual(missing["reason"], "replacement_missing_boundary_change")
        self.assertEqual(admitted["decision"], "admit")
        self.assertTrue(admitted["score_eligible"])

    def test_index_deduplicates_the_same_preserved_job(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = self._history(Path(first))
            second_root = self._history(Path(second))
            index = build_history_index([first_root, second_root])
        self.assertEqual(len(index["records"]), 1)
        self.assertEqual(validate_history_index(index), [])

    def test_job_prefix_filter_and_receipt_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = build_history_index(
                [self._history(Path(temp_dir))],
                job_name_prefixes=["tb3-"],
            )
        self.assertEqual(index["records"], [])
        receipt = build_history_receipt(
            index=index,
            task="sample-task",
            job_name="tb3-new-job",
            agent_name="direct-agent",
            model="model-x",
            codex_version="0.149.1",
            evidence_class="fresh_direct",
        )
        self.assertEqual(validate_history_receipt(receipt), [])
        receipt["unknown"] = True
        self.assertTrue(
            any("unknown receipt fields" in error for error in validate_history_receipt(receipt))
        )

    def test_cli_rejects_duplicate_before_harbor_or_auth_checks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        runner = repo_root / ".statem" / "benchmarks" / "run_harbor_batch.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index = build_history_index(
                [
                    self._history(
                        root / "history", task="terminal-bench/sample-task"
                    )
                ]
            )
            index_path = root / "history.json"
            receipt_path = root / "receipt.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--task",
                    "terminal-bench/sample-task",
                    "--job-name",
                    "new-job",
                    "--model",
                    "model-x",
                    "--agent-name",
                    "direct-agent",
                    "--agent-kwarg",
                    "version=0.149.1",
                    "--prelaunch-history-index",
                    str(index_path),
                    "--prelaunch-evidence-class",
                    "fresh_direct",
                    "--prelaunch-history-receipt",
                    str(receipt_path),
                    "--no-prelaunch-task-field-check",
                    "--prelaunch-only",
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["decision"], "reject")
            self.assertEqual(
                receipt["reason"], "prior_reward_valid_direct_observation"
            )


if __name__ == "__main__":
    unittest.main()
