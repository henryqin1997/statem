from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from integrations.teamrun.teamrun_codex_workers import _bounded_wall_timeout
from integrations.teamrun.teamrun_lifecycle import (
    cancel_lifecycle,
    join_lifecycle,
    lifecycle_status,
    require_completed_lifecycle,
    spawn_lifecycle,
)


class TeamRunLifecycleTest(unittest.TestCase):
    def test_detached_child_records_terminal_state_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handle = Path(temp_dir) / "worker.json"
            spawned = spawn_lifecycle(
                loop_args=[
                    "--run-id",
                    "run-1",
                    "--entry-id",
                    "entry-1",
                    "--worker-command",
                    "true",
                    "--max-rounds",
                    "0",
                    "--json",
                ],
                handle_file=handle,
                run_id="run-1",
                entry_id="entry-1",
                wall_timeout=5,
            )
            self.assertEqual(spawned["state"], "running")
            joined = join_lifecycle(
                handle,
                run_id="run-1",
                entry_id="entry-1",
                timeout=5,
            )
            self.assertEqual(joined["state"], "completed")
            self.assertEqual(joined["returncode"], 0)
            self.assertEqual(
                require_completed_lifecycle(
                    handle, run_id="run-1", entry_id="entry-1"
                )["handle_id"],
                joined["handle_id"],
            )
            with self.assertRaisesRegex(ValueError, "another entry"):
                join_lifecycle(
                    handle,
                    run_id="run-1",
                    entry_id="entry-2",
                    timeout=0,
                )

    def test_cancel_is_idempotent_for_terminal_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handle = Path(temp_dir) / "worker.json"
            spawn_lifecycle(
                loop_args=[
                    "--run-id",
                    "run-2",
                    "--entry-id",
                    "entry-2",
                    "--worker-command",
                    "true",
                    "--max-rounds",
                    "0",
                ],
                handle_file=handle,
                run_id="run-2",
                entry_id="entry-2",
                wall_timeout=5,
            )
            joined = join_lifecycle(
                handle,
                run_id="run-2",
                entry_id="entry-2",
                timeout=5,
            )
            canceled = cancel_lifecycle(
                handle,
                run_id="run-2",
                entry_id="entry-2",
                reason="cleanup",
            )
            self.assertEqual(canceled["state"], joined["state"])
            self.assertEqual(lifecycle_status(handle)["state"], "completed")

    def test_global_deadline_caps_relative_wall_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            deadline = Path(temp_dir) / "deadline.json"
            deadline.write_text(
                json.dumps({"deadline_at_epoch": time.time() + 300}),
                encoding="utf-8",
            )
            bounded = _bounded_wall_timeout(
                900,
                deadline_file=deadline,
                reserve_seconds=120,
            )
            self.assertIsNotNone(bounded)
            self.assertGreater(bounded, 170)
            self.assertLessEqual(bounded, 180)


if __name__ == "__main__":
    unittest.main()
