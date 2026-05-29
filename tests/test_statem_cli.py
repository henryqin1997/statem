from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class StatemCliTest(unittest.TestCase):
    def run_statem(
        self, *args: str, check: bool = True, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        completed = subprocess.run(
            [sys.executable, "-m", "statem", *args],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
            env=process_env,
        )
        if check and completed.returncode != 0:
            self.fail(
                "statem command failed\n"
                f"args: {args}\n"
                f"returncode: {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed

    def run_stop_hook(self, payload: dict[str, object], check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        existing_path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(REPO) if not existing_path else str(REPO) + os.pathsep + existing_path
        env["STATEM_COMMAND"] = f"{sys.executable} -m statem"
        completed = subprocess.run(
            [sys.executable, str(REPO / "integrations/hooks/statem_stop_hook.py")],
            cwd=REPO,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        if check and completed.returncode != 0:
            self.fail(
                "statem stop hook failed\n"
                f"payload: {payload}\n"
                f"returncode: {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed

    def test_goto_blocks_until_predicate_passes_and_save_runs_out_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "loop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: test-loop
initial: start
nodes:
  start:
    prompt: |
      Load task context.
    before_transfer:
      type: predicate
      path: progress.md
      exists: true
      non_empty: true
  plan:
    prompt: Write the plan.
    out_hook:
      type: command
      run: touch saved.txt
edges:
  - from: start
    to: plan
    condition: "Task context is loaded."
""".strip()
                + "\n",
                encoding="utf-8",
            )

            validate = self.run_statem("validate", str(spec), "--json")
            self.assertTrue(json.loads(validate.stdout)["ok"])

            start = self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "run1",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
            )
            self.assertEqual(json.loads(start.stdout)["current"], "start")

            blocked = self.run_statem(
                "goto",
                "plan",
                "--run-id",
                "run1",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(blocked.stdout)
            self.assertIn("blocked", blocked_payload["error"])
            self.assertEqual(blocked_payload["details"]["stage"], "before_transfer")
            self.assertEqual(blocked_payload["details"]["results"][0]["type"], "predicate")
            self.assertIn("file does not exist", blocked_payload["details"]["results"][0]["output"])

            cur = self.run_statem("cur", "--run-id", "run1", "--state-dir", str(state_dir), "--json")
            self.assertEqual(json.loads(cur.stdout)["current"], "start")

            (root / "progress.md").write_text("planned\n", encoding="utf-8")
            moved = self.run_statem(
                "goto",
                "plan",
                "--run-id",
                "run1",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
            )
            self.assertEqual(json.loads(moved.stdout)["current"], "plan")

            self.run_statem("save", "--run-id", "run1", "--state-dir", str(state_dir), "--json")
            self.assertTrue((root / "saved.txt").exists())

    def test_state_dir_can_come_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "env-state.yaml"
            state_dir = root / "machine-state"
            spec.write_text(
                """
name: env-state
initial: start
nodes:
  start:
    prompt: Start.
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )

            env = {"STATEM_STATE_DIR": str(state_dir)}
            started = self.run_statem("start", str(spec), "--run-id", "env-run", "--json", env=env)
            self.assertEqual(json.loads(started.stdout)["current"], "start")
            self.assertTrue((state_dir / "active_run").exists())
            self.assertFalse((root / ".statem").exists())

            cur = self.run_statem("cur", "--run-id", "env-run", "--json", env=env)
            self.assertEqual(json.loads(cur.stdout)["current"], "start")

    def test_json_file_predicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "json-loop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: json-loop
initial: plan
nodes:
  plan:
    prompt: Review plan.
  execute:
    prompt: Execute.
edges:
  - from: plan
    to: execute
    condition:
      type: predicate
      path: checks.json
      json_path: plan.reviewed
      equals: true
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (root / "checks.json").write_text('{"plan": {"reviewed": true}}\n', encoding="utf-8")

            self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "json-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            moved = self.run_statem(
                "goto",
                "execute",
                "--run-id",
                "json-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            self.assertEqual(json.loads(moved.stdout)["current"], "execute")

    def test_command_hooks_block_and_run_edge_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "command-loop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: command-loop
initial: start
nodes:
  start:
    prompt: Prepare command gate.
    before_transfer:
      type: command
      run: test -f gate.txt
  done:
    prompt: Done.
edges:
  - from: start
    to: done
    hook:
      type: command
      run: touch edge-hook-ran.txt
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "cmd-run", "--state-dir", str(state_dir), "--json")
            blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "cmd-run",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(blocked.stdout)
            self.assertEqual(blocked_payload["details"]["stage"], "before_transfer")
            self.assertEqual(blocked_payload["details"]["results"][0]["type"], "command")
            self.assertEqual(blocked_payload["details"]["results"][0]["exit_code"], 1)
            self.assertFalse((root / "edge-hook-ran.txt").exists())

            (root / "gate.txt").write_text("ok\n", encoding="utf-8")
            moved = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "cmd-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            self.assertEqual(json.loads(moved.stdout)["current"], "done")
            self.assertTrue((root / "edge-hook-ran.txt").exists())

    def test_in_hook_sees_persisted_target_state_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "persisted-in-hook.json"
            state_dir = root / ".statem"
            command = (
                "python3 -c \"import json, os, pathlib; "
                "path=pathlib.Path(os.environ['STATEM_STATE_DIR']) / 'runs' / "
                "os.environ['STATEM_RUN_ID'] / 'state.json'; "
                "print(os.environ['STATEM_CURRENT'] + ':' + json.load(open(path))['current'])\" "
                "> seen-current.txt"
            )
            spec.write_text(
                json.dumps(
                    {
                        "name": "persisted-in-hook",
                        "initial": "start",
                        "nodes": {
                            "start": {"prompt": "Start."},
                            "done": {"prompt": "Done.", "in_hook": {"type": "command", "run": command}},
                        },
                        "edges": [{"from": "start", "to": "done"}],
                    }
                ),
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "persist-run", "--state-dir", str(state_dir), "--json")
            self.run_statem("goto", "done", "--run-id", "persist-run", "--state-dir", str(state_dir), "--json")
            self.assertEqual((root / "seen-current.txt").read_text(encoding="utf-8").strip(), "done:done")

    def test_failed_edge_hook_stays_at_source_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "edge-hook-retry.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: edge-hook-retry
initial: start
nodes:
  start:
    prompt: Start.
    out_hook:
      type: command
      run: touch out-hook-ran.txt
  done:
    prompt: Done.
edges:
  - from: start
    to: done
    hook:
      type: command
      run: test -f transfer-ready.txt
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "retry-run", "--state-dir", str(state_dir), "--json")
            blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "retry-run",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertTrue((root / "out-hook-ran.txt").exists())
            cur = self.run_statem("cur", "--run-id", "retry-run", "--state-dir", str(state_dir), "--json")
            self.assertEqual(json.loads(cur.stdout)["current"], "start")

            (root / "transfer-ready.txt").write_text("ready\n", encoding="utf-8")
            moved = self.run_statem("goto", "done", "--run-id", "retry-run", "--state-dir", str(state_dir), "--json")
            self.assertEqual(json.loads(moved.stdout)["current"], "done")

    def test_llm_review_runs_external_reviewer_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "review-loop.json"
            state_dir = root / ".statem"
            spec.write_text(
                json.dumps(
                    {
                        "name": "review-loop",
                        "initial": "plan",
                        "nodes": {
                            "plan": {"prompt": "Prepare a plan."},
                            "execute": {"prompt": "Execute the plan."},
                        },
                        "edges": [
                            {
                                "from": "plan",
                                "to": "execute",
                                "condition": {
                                    "type": "llm_review",
                                    "prompt": "Review readiness before execution.",
                                    "run": (
                                        "python3 -c \"import sys; "
                                        "data=sys.stdin.read(); "
                                        "print('APPROVED' if 'Review readiness' in data else 'NO')\""
                                    ),
                                    "accept_contains": "APPROVED",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "review-run", "--state-dir", str(state_dir), "--json")
            moved = self.run_statem(
                "goto",
                "execute",
                "--run-id",
                "review-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            payload = json.loads(moved.stdout)
            self.assertEqual(payload["current"], "execute")
            self.assertTrue(any(result["type"] == "llm_review" for result in payload["results"]))

    def test_start_migrates_spec_edits_and_reruns_in_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "editable.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: editable
initial: start
nodes:
  start:
    prompt: Start.
  plan:
    prompt: Plan.
edges:
  - from: start
    to: plan
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "edit-run", "--state-dir", str(state_dir), "--json")
            self.run_statem("goto", "plan", "--run-id", "edit-run", "--state-dir", str(state_dir), "--json")

            spec.write_text(
                """
name: editable
initial: start
nodes:
  start:
    prompt: Start.
  plan:
    prompt: Plan.
    in_hook:
      type: command
      run: echo resumed >> entered.log
edges:
  - from: start
    to: plan
""".strip()
                + "\n",
                encoding="utf-8",
            )
            resumed = self.run_statem("start", str(spec), "--run-id", "edit-run", "--state-dir", str(state_dir), "--json")
            self.assertEqual(json.loads(resumed.stdout)["current"], "plan")
            self.assertIn("resumed", (root / "entered.log").read_text(encoding="utf-8"))

            spec.write_text(
                """
name: editable
initial: start
nodes:
  start:
    prompt: Start again.
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )
            migrated = self.run_statem("start", str(spec), "--run-id", "edit-run", "--state-dir", str(state_dir), "--json")
            self.assertEqual(json.loads(migrated.stdout)["current"], "start")
            history = self.run_statem("history", "--run-id", "edit-run", "--state-dir", str(state_dir), "--json")
            events = [event["event"] for event in json.loads(history.stdout)["history"]]
            self.assertIn("migrate_current", events)

            tail = self.run_statem("history", "--run-id", "edit-run", "--state-dir", str(state_dir), "--tail", "1", "--json")
            tail_events = json.loads(tail.stdout)["history"]
            self.assertEqual(len(tail_events), 1)
            self.assertEqual(tail_events[0]["event"], "in_hook")

    def test_prompt_generates_post_clear_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "prompt-loop.yaml"
            state_dir = root / ".statem with spaces"
            spec.write_text(
                """
name: prompt-loop
initial: start
nodes:
  start:
    prompt: Start.
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "prompt-run", "--state-dir", str(state_dir), "--json")
            rendered = self.run_statem("prompt", "--run-id", "prompt-run", "--state-dir", str(state_dir))
            self.assertIn("after a context clear", rendered.stdout)
            self.assertIn("statem start", rendered.stdout)
            self.assertNotIn("python3 -m statem", rendered.stdout)
            self.assertIn("--run-id prompt-run", rendered.stdout)
            self.assertIn("--state-dir", rendered.stdout)
            self.assertIn("'{}'".format(state_dir.resolve()), rendered.stdout)

            payload = self.run_statem("prompt", "--run-id", "prompt-run", "--state-dir", str(state_dir), "--json")
            self.assertIn("statem history", json.loads(payload.stdout)["prompt"])
            self.assertIn("--tail 8", json.loads(payload.stdout)["prompt"])

    def test_compact_prompt_generates_loop_hygiene_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "compact-loop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: compact-loop
initial: review
nodes:
  review:
    prompt: Review.
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "compact-run", "--state-dir", str(state_dir), "--json")
            rendered = self.run_statem("compact-prompt", "--run-id", "compact-run", "--state-dir", str(state_dir))
            self.assertIn("/compact", rendered.stdout)
            self.assertIn("stale failed attempts", rendered.stdout)
            self.assertIn("statem cur", rendered.stdout)
            self.assertNotIn("python3 -m statem", rendered.stdout)
            self.assertIn("compact-run", rendered.stdout)

            payload = self.run_statem("compact-prompt", "--run-id", "compact-run", "--state-dir", str(state_dir), "--json")
            self.assertIn("Discard:", json.loads(payload.stdout)["prompt"])
            self.assertIn("--tail 8", json.loads(payload.stdout)["prompt"])

    def test_help_mentions_loop_hygiene(self) -> None:
        help_text = self.run_statem("--help").stdout
        self.assertIn("compact-prompt", help_text)
        self.assertIn("Loop hygiene", help_text)

    def test_stop_hook_blocks_unfinished_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "autoloop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: autoloop
initial: start
nodes:
  start:
    prompt: Keep working.
  review:
    prompt: Review.
edges:
  - from: start
    to: review
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "auto-run", "--state-dir", str(state_dir), "--json")
            completed = self.run_stop_hook({"cwd": str(root), "stop_hook_active": False})
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("Continue the active statem-managed run", payload["reason"])
            self.assertIn("statem cur", payload["reason"])
            self.assertIn("Current state: start", payload["reason"])

    def test_stop_hook_allows_recursion_guard_and_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "handoff.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: handoff-loop
initial: start
nodes:
  start:
    prompt: Work.
  handoff:
    prompt: Handoff to user.
edges:
  - from: start
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "handoff-run", "--state-dir", str(state_dir), "--json")
            guarded = self.run_stop_hook({"cwd": str(root), "stop_hook_active": True})
            self.assertEqual(guarded.stdout, "")

            self.run_statem("goto", "handoff", "--run-id", "handoff-run", "--state-dir", str(state_dir), "--json")
            terminal = self.run_stop_hook({"cwd": str(root), "stop_hook_active": False})
            self.assertEqual(terminal.stdout, "")


if __name__ == "__main__":
    unittest.main()
