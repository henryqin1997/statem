from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def run_stop_hook(
        self,
        payload: dict[str, object],
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        existing_path = process_env.get("PYTHONPATH")
        process_env["PYTHONPATH"] = str(REPO) if not existing_path else str(REPO) + os.pathsep + existing_path
        process_env["STATEM_COMMAND"] = f"{sys.executable} -m statem"
        completed = subprocess.run(
            [sys.executable, str(REPO / "integrations/hooks/statem_stop_hook.py")],
            cwd=REPO,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=process_env,
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

    def test_optional_edge_max_attempts_bounds_only_configured_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            limited_spec = root / "limited.yaml"
            unlimited_spec = root / "unlimited.yaml"
            state_dir = root / ".statem"
            template = """
name: attempt-limit
initial: start
nodes:
  start:
    before_transfer:
      type: predicate
      path: ready.txt
      exists: true
  done: Done.
edges:
  - from: start
    to: done
{limit}
""".strip()
            limited_spec.write_text(template.format(limit="    max_attempts: 2") + "\n", encoding="utf-8")
            unlimited_spec.write_text(template.format(limit="") + "\n", encoding="utf-8")

            validated = json.loads(self.run_statem("validate", str(limited_spec), "--json").stdout)
            self.assertEqual(validated["edges"][0]["max_attempts"], 2)
            self.run_statem(
                "start",
                str(limited_spec),
                "--run-id",
                "limited",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            for attempt in (1, 2):
                blocked = self.run_statem(
                    "goto",
                    "done",
                    "--run-id",
                    "limited",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                    check=False,
                )
                self.assertEqual(blocked.returncode, 2)
                details = json.loads(blocked.stdout)["details"]
                self.assertEqual(details["stage"], "before_transfer")
                self.assertEqual(details["attempt"], attempt)
                self.assertEqual(details["max_attempts"], 2)
                self.assertEqual(details["attempts_remaining"], 2 - attempt)

            exhausted = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "limited",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(exhausted.returncode, 2)
            exhausted_details = json.loads(exhausted.stdout)["details"]
            self.assertEqual(exhausted_details["stage"], "max_attempts")
            self.assertEqual(exhausted_details["attempts_used"], 2)
            self.assertEqual(exhausted_details["results"], [])

            self.run_statem(
                "start",
                str(unlimited_spec),
                "--run-id",
                "unlimited",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            for _ in range(3):
                blocked = self.run_statem(
                    "goto",
                    "done",
                    "--run-id",
                    "unlimited",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                    check=False,
                )
                self.assertEqual(blocked.returncode, 2)
                details = json.loads(blocked.stdout)["details"]
                self.assertEqual(details["stage"], "before_transfer")
                self.assertNotIn("max_attempts", details)

    def test_edge_max_attempts_must_be_a_positive_integer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, value in enumerate(("0", "-1", "true", '"2"'), start=1):
                spec = root / f"invalid-{index}.yaml"
                spec.write_text(
                    f"""
name: invalid-attempt-limit
initial: start
nodes:
  start: Start.
  done: Done.
edges:
  - from: start
    to: done
    max_attempts: {value}
""".strip()
                    + "\n",
                    encoding="utf-8",
                )
                rejected = self.run_statem("validate", str(spec), "--json", check=False)
                self.assertEqual(rejected.returncode, 1)
                self.assertIn("max_attempts must be a positive integer", json.loads(rejected.stdout)["error"])

    def test_validate_strict_rejects_unknown_keywords_at_every_runbook_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "strict-keywords.yaml"
            spec.write_text(
                """
namme: strict-keywords
initial: start
nodes:
  start:
    prompt: Start.
    before_transfr:
      type: predicate
      path: ready.txt
    dynamic_before_transfer:
      required: false
      min_itemz: 0
    multi_agent:
      required: false
      max_paralel: 1
      task_schema:
        requiredd: []
      reducer:
        strateggy: all-claims-table
    state_hooks:
      - name: continue_start
        event: stop
        templat: statem_autoloop
  done: Done.
edges:
  - from: start
    to: done
    max_atempts: 2
    before_transfer:
      type: predicate
      path: misplaced.txt
    condition:
      type: command
      run: "true"
      timout: 1
""".strip()
                + "\n",
                encoding="utf-8",
            )

            permissive = self.run_statem("validate", str(spec), "--json")
            self.assertTrue(json.loads(permissive.stdout)["ok"])

            strict = self.run_statem("validate", str(spec), "--strict", "--json", check=False)
            self.assertEqual(strict.returncode, 1)
            error = json.loads(strict.stdout)["error"]
            for keyword in (
                "namme",
                "before_transfr",
                "min_itemz",
                "max_paralel",
                "requiredd",
                "strateggy",
                "templat",
                "max_atempts",
                "before_transfer",
                "timout",
            ):
                self.assertIn(keyword, error)
            self.assertIn("did you mean 'before_transfer'?", error)
            self.assertIn("did you mean 'max_attempts'?", error)

    def test_validate_strict_accepts_supported_nested_keywords(self) -> None:
        for spec in (
            "examples/coding-agent.yaml",
            "examples/teamrun-video-search/runbook.yaml",
        ):
            validated = self.run_statem("validate", spec, "--strict", "--json")
            payload = json.loads(validated.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["strict"])

    def test_coding_agent_example_uses_repo_progress_file(self) -> None:
        progress = REPO / "progress.md"
        original = progress.read_text(encoding="utf-8") if progress.exists() else None
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / ".statem"
            try:
                progress.write_text("example progress\n", encoding="utf-8")
                self.run_statem(
                    "start",
                    "examples/coding-agent.yaml",
                    "--run-id",
                    "coding-example",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                )
                self.run_statem(
                    "goto",
                    "plan",
                    "--run-id",
                    "coding-example",
                    "--state-dir",
                    str(state_dir),
                    "--yes",
                    "--json",
                )
                moved = self.run_statem(
                    "goto",
                    "execute",
                    "--run-id",
                    "coding-example",
                    "--state-dir",
                    str(state_dir),
                    "--yes",
                    "--json",
                )
            finally:
                if original is None:
                    progress.unlink(missing_ok=True)
                else:
                    progress.write_text(original, encoding="utf-8")

        payload = json.loads(moved.stdout)
        self.assertEqual(payload["current"], "execute")
        predicate_outputs = [
            result["output"]
            for result in payload["results"]
            if result["type"] == "predicate"
        ]
        self.assertTrue(any(str(progress) in output for output in predicate_outputs))

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

    def test_dynamic_before_transfer_retries_same_entry_and_snapshots_latest_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "dynamic-loop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: dynamic-loop
initial: execute
nodes:
  execute:
    prompt: Execute.
    dynamic_before_transfer:
      path: current_entry
      required: true
      min_items: 1
      require_reason: true
      require_basis: true
      allow_types:
        - manual
        - predicate
      stale_policy: require_confirmation
  review:
    prompt: Review.
edges:
  - from: execute
    to: review
  - from: review
    to: execute
""".strip()
                + "\n",
                encoding="utf-8",
            )

            started = self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "dynamic-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            first_entry = json.loads(started.stdout)["current_entry_id"]

            path_payload = json.loads(
                self.run_statem(
                    "dynamic",
                    "path",
                    "--run-id",
                    "dynamic-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "agent-a",
                    "--agent-role",
                    "executor",
                    "--json",
                ).stdout
            )
            self.assertEqual(path_payload["current_entry_id"], first_entry)
            dynamic_dir = Path(path_payload["path"])

            checks_file = root / "checks.json"
            checks_file.write_text(
                json.dumps(
                    {
                        "basis": {"implementation_summary": "First approach requires proof.txt."},
                        "checks": [
                            {
                                "type": "predicate",
                                "path": "proof.txt",
                                "exists": True,
                                "non_empty": True,
                                "reason": "The first approach records durable proof.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            written = json.loads(
                self.run_statem(
                    "dynamic",
                    "write",
                    str(checks_file),
                    "--run-id",
                    "dynamic-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "agent-a",
                    "--agent-role",
                    "executor",
                    "--json",
                ).stdout
            )
            self.assertEqual(written["checks"], 1)
            self.assertTrue((dynamic_dir / "checks.agent-a.json").exists())

            spoof_file = root / "spoof.json"
            spoof_file.write_text(
                json.dumps(
                    {
                        "producer": {"agent_id": "spoofed-agent", "role": "spoofed-role"},
                        "basis": {"implementation_summary": "Producer metadata should be command-owned."},
                        "checks": [
                            {
                                "type": "manual",
                                "prompt": "Confirm producer metadata is normalized.",
                                "reason": "The CLI agent id should own the written check file.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.run_statem(
                "dynamic",
                "write",
                str(spoof_file),
                "--run-id",
                "dynamic-run",
                "--state-dir",
                str(state_dir),
                "--agent-id",
                "agent-b",
                "--agent-role",
                "reviewer",
                "--json",
            )
            producers = json.loads(
                self.run_statem(
                    "dynamic",
                    "list",
                    "--run-id",
                    "dynamic-run",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )["producers"]
            producer_ids = {item["producer"]["agent_id"] for item in producers}
            self.assertIn("agent-b", producer_ids)
            self.assertNotIn("spoofed-agent", producer_ids)

            blocked = self.run_statem(
                "goto",
                "review",
                "--run-id",
                "dynamic-run",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(blocked.stdout)
            self.assertEqual(blocked_payload["details"]["stage"], "dynamic_before_transfer")
            self.assertEqual(blocked_payload["details"]["current_entry_id"], first_entry)

            cur_after_block = json.loads(
                self.run_statem("cur", "--run-id", "dynamic-run", "--state-dir", str(state_dir), "--json").stdout
            )
            self.assertEqual(cur_after_block["current"], "execute")
            self.assertEqual(cur_after_block["current_entry_id"], first_entry)

            checks_file.write_text(
                json.dumps(
                    {
                        "basis": {"implementation_summary": "Second approach uses manual verification."},
                        "checks": [
                            {
                                "type": "manual",
                                "prompt": "Confirm second approach was verified.",
                                "reason": "The implementation approach changed after the failed check.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.run_statem(
                "dynamic",
                "write",
                str(checks_file),
                "--run-id",
                "dynamic-run",
                "--state-dir",
                str(state_dir),
                "--agent-id",
                "agent-a",
                "--agent-role",
                "executor",
                "--json",
            )
            moved = json.loads(
                self.run_statem(
                    "goto",
                    "review",
                    "--run-id",
                    "dynamic-run",
                    "--state-dir",
                    str(state_dir),
                    "--yes",
                    "--json",
                ).stdout
            )
            self.assertEqual(moved["current"], "review")

            history = json.loads(
                self.run_statem("history", "--run-id", "dynamic-run", "--state-dir", str(state_dir), "--json").stdout
            )
            dynamic_events = [event for event in history["history"] if event["event"] == "dynamic_before_transfer"]
            self.assertEqual(len(dynamic_events), 2)
            self.assertEqual(dynamic_events[0]["checks_snapshot"][0]["type"], "predicate")
            self.assertEqual(dynamic_events[1]["checks_snapshot"][0]["type"], "manual")

            back = json.loads(
                self.run_statem(
                    "goto",
                    "execute",
                    "--run-id",
                    "dynamic-run",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertNotEqual(back["current_entry_id"], first_entry)

    def test_dynamic_before_transfer_blocks_disallowed_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "dynamic-types.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: dynamic-types
initial: execute
nodes:
  execute:
    prompt: Execute.
    dynamic_before_transfer:
      path: current_entry
      required: true
      min_items: 1
      require_reason: true
      require_basis: true
      allow_types:
        - manual
        - predicate
  done:
    prompt: Done.
edges:
  - from: execute
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem("start", str(spec), "--run-id", "type-run", "--state-dir", str(state_dir), "--json")
            checks_file = root / "checks.json"
            checks_file.write_text(
                json.dumps(
                    {
                        "basis": {"implementation_summary": "This intentionally tries a command check."},
                        "checks": [
                            {
                                "type": "command",
                                "run": "touch should-not-run.txt",
                                "reason": "Command checks are not allowed by this state.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rejected_write = self.run_statem(
                "dynamic",
                "write",
                str(checks_file),
                "--run-id",
                "type-run",
                "--state-dir",
                str(state_dir),
                "--agent-id",
                "agent-a",
                "--json",
                check=False,
            )
            self.assertEqual(rejected_write.returncode, 1)
            error = json.loads(rejected_write.stdout)["error"]
            self.assertIn("not allowed", error)
            self.assertIn("Accepted dynamic checks file shape", error)
            self.assertIn("Allowed dynamic check types", error)
            self.assertIn("{'type': 'manual'", error)
            self.assertIn("{'type': 'predicate'", error)
            self.assertNotIn("{'type': 'command', 'run'", error)
            self.assertNotIn("{'type': 'checklist'", error)

            dynamic_path = json.loads(
                self.run_statem(
                    "dynamic",
                    "path",
                    "--run-id",
                    "type-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "agent-a",
                    "--json",
                ).stdout
            )["path"]
            (Path(dynamic_path) / "checks.agent-a.json").write_text(checks_file.read_text(encoding="utf-8"), encoding="utf-8")
            blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "type-run",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            payload = json.loads(blocked.stdout)
            self.assertEqual(payload["details"]["stage"], "dynamic_before_transfer")
            self.assertIn("not allowed", payload["details"]["results"][0]["output"])
            self.assertFalse((root / "should-not-run.txt").exists())

    def test_dynamic_write_help_includes_schema_hint(self) -> None:
        help_result = self.run_statem("dynamic", "write", "--help")
        self.assertIn("Accepted dynamic checks file shape", help_result.stdout)
        self.assertIn("implementation_summary", help_result.stdout)
        self.assertIn("--agent-id", help_result.stdout)

    def test_manual_checklist_block_has_pending_confirmation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "manual-summary.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: manual-summary
initial: start
nodes:
  start:
    prompt: Start.
    before_transfer:
      type: checklist
      items:
        - Automatic command passed
        - Human reviewed the result
  done:
    prompt: Done.
edges:
  - from: start
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem("start", str(spec), "--run-id", "manual-run", "--state-dir", str(state_dir), "--json")
            blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "manual-run",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            payload = json.loads(blocked.stdout)
            self.assertIn("manual confirmation is pending", payload["details"]["summary"])
            self.assertEqual(payload["details"]["pending_confirmation"][0]["type"], "checklist")

            human_blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "manual-run",
                "--state-dir",
                str(state_dir),
                check=False,
            )
            self.assertEqual(human_blocked.returncode, 2)
            self.assertIn("manual confirmation is pending", human_blocked.stderr)

    def test_advisory_checklist_does_not_require_yes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "advisory-checklist.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: advisory-checklist
initial: start
nodes:
  start:
    prompt: Start.
    before_transfer:
      type: checklist
      confirmation: none
      items:
        - Artifact exists
        - Evidence was recorded
  done:
    prompt: Done.
edges:
  - from: start
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            validate = self.run_statem("validate", str(spec), "--json")
            self.assertTrue(json.loads(validate.stdout)["ok"])

            self.run_statem("start", str(spec), "--run-id", "advisory-run", "--state-dir", str(state_dir), "--json")
            moved = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "advisory-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            payload = json.loads(moved.stdout)
            self.assertEqual(payload["current"], "done")
            self.assertIn("checklist confirmation not required", payload["results"][0]["output"])

    def test_dynamic_before_transfer_blocks_missing_registered_producer_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "dynamic-missing.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: dynamic-missing
initial: execute
nodes:
  execute:
    prompt: Execute.
    dynamic_before_transfer:
      path: current_entry
      required: true
      min_items: 1
      require_reason: true
      allow_types:
        - manual
  done:
    prompt: Done.
edges:
  - from: execute
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem("start", str(spec), "--run-id", "missing-run", "--state-dir", str(state_dir), "--json")
            checks_file = root / "checks.json"
            checks_file.write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "type": "manual",
                                "prompt": "Confirm registered producer check.",
                                "reason": "This producer file should not disappear silently.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            written = json.loads(
                self.run_statem(
                    "dynamic",
                    "write",
                    str(checks_file),
                    "--run-id",
                    "missing-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "agent-a",
                    "--json",
                ).stdout
            )
            Path(written["path"]).unlink()

            blocked = self.run_statem(
                "goto",
                "done",
                "--run-id",
                "missing-run",
                "--state-dir",
                str(state_dir),
                "--yes",
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            payload = json.loads(blocked.stdout)
            self.assertEqual(payload["details"]["stage"], "dynamic_before_transfer")
            self.assertIn("registered but its checks file is missing", payload["details"]["results"][0]["output"])

    def test_dynamic_agent_ids_with_unsafe_chars_do_not_collapse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "dynamic-agent-id.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: dynamic-agent-id
initial: execute
nodes:
  execute:
    prompt: Execute.
    dynamic_before_transfer:
      path: current_entry
      required: true
      min_items: 2
      require_reason: true
      allow_types:
        - manual
  done:
    prompt: Done.
edges:
  - from: execute
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem("start", str(spec), "--run-id", "agent-id-run", "--state-dir", str(state_dir), "--json")
            checks_file = root / "checks.json"
            checks_file.write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "type": "manual",
                                "prompt": "Confirm agent-specific check.",
                                "reason": "Each agent id should map to a distinct safe filename.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            first = json.loads(
                self.run_statem(
                    "dynamic",
                    "write",
                    str(checks_file),
                    "--run-id",
                    "agent-id-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "team/a",
                    "--json",
                ).stdout
            )
            second = json.loads(
                self.run_statem(
                    "dynamic",
                    "write",
                    str(checks_file),
                    "--run-id",
                    "agent-id-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "team-a",
                    "--json",
                ).stdout
            )
            self.assertNotEqual(first["agent_id"], second["agent_id"])
            self.assertNotEqual(first["path"], second["path"])

    def test_in_hook_sees_persisted_target_state_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "persisted-in-hook.json"
            state_dir = root / ".statem"
            command = (
                "python3 -c \"import json, os, pathlib; "
                "path=pathlib.Path(os.environ['STATEM_STATE_DIR']) / 'runs' / "
                "os.environ['STATEM_RUN_ID'] / 'state.json'; "
                "state=json.load(open(path)); "
                "print(os.environ['STATEM_CURRENT'] + ':' + state['current'] + ':' + "
                "os.environ['STATEM_ENTRY_ID'] + ':' + state['current_entry_id'] + ':' + "
                "os.environ['STATEM_AGENT_ID'] + ':' + os.environ['STATEM_AGENT_ROLE'])\" "
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
            transitioned = json.loads(
                self.run_statem(
                    "goto",
                    "done",
                    "--run-id",
                    "persist-run",
                    "--state-dir",
                    str(state_dir),
                    "--agent-id",
                    "lead-1",
                    "--agent-role",
                    "solver",
                    "--json",
                ).stdout
            )
            entry_id = transitioned["current_entry_id"]
            self.assertEqual(
                (root / "seen-current.txt").read_text(encoding="utf-8").strip(),
                f"done:done:{entry_id}:{entry_id}:lead-1:solver",
            )

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
            self.assertIn("Use exactly this statem run id: compact-run", rendered.stdout)
            self.assertIn("Ignore every older statem run id", rendered.stdout)
            self.assertIn("statem cur", rendered.stdout)
            self.assertNotIn("python3 -m statem", rendered.stdout)
            self.assertIn("compact-run", rendered.stdout)

            payload = self.run_statem("compact-prompt", "--run-id", "compact-run", "--state-dir", str(state_dir), "--json")
            self.assertIn("Discard:", json.loads(payload.stdout)["prompt"])
            self.assertIn("different --run-id", json.loads(payload.stdout)["prompt"])
            self.assertIn("--tail 8", json.loads(payload.stdout)["prompt"])

    def test_help_mentions_loop_hygiene(self) -> None:
        help_text = self.run_statem("--help").stdout
        self.assertIn("compact-prompt", help_text)
        self.assertIn("Loop hygiene", help_text)

    def test_state_hooks_are_active_only_for_current_state_and_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "state-hooks.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: state-hooks
initial: execute
nodes:
  execute:
    prompt: Execute.
    state_hooks:
      - name: keep_executing
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
        prompt: "Check progress and continue execution unless blocked."
  handoff:
    prompt: Handoff.
edges:
  - from: execute
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            started = json.loads(
                self.run_statem(
                    "start",
                    str(spec),
                    "--run-id",
                    "hook-run",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            first_entry = started["current_entry_id"]
            self.assertEqual(started["state_hooks"][0]["name"], "keep_executing")
            self.assertEqual(started["state_hooks"][0]["entry_id"], first_entry)

            active = json.loads(
                self.run_statem(
                    "hooks",
                    "active",
                    "--run-id",
                    "hook-run",
                    "--state-dir",
                    str(state_dir),
                    "--event",
                    "stop",
                    "--host",
                    "codex",
                    "--json",
                ).stdout
            )
            self.assertEqual(active["hooks"][0]["name"], "keep_executing")
            self.assertEqual(active["hooks"][0]["entry_id"], first_entry)

            blocked = json.loads(
                self.run_statem(
                    "hooks",
                    "run",
                    "stop",
                    "--run-id",
                    "hook-run",
                    "--state-dir",
                    str(state_dir),
                    "--host",
                    "codex",
                    "--command",
                    "python3 -m statem",
                    "--json",
                ).stdout
            )
            self.assertEqual(blocked["matched_hooks"], 1)
            self.assertEqual(blocked["decision"], "block")
            self.assertIn("State hook: keep_executing", blocked["reason"])
            self.assertIn("python3 -m statem cur", blocked["reason"])
            history_after_hook = json.loads(
                self.run_statem("history", "--run-id", "hook-run", "--state-dir", str(state_dir), "--json").stdout
            )
            self.assertIn("state_hook", [event["event"] for event in history_after_hook["history"]])

            self.run_statem("goto", "handoff", "--run-id", "hook-run", "--state-dir", str(state_dir), "--json")
            active_after = json.loads(
                self.run_statem(
                    "hooks",
                    "active",
                    "--run-id",
                    "hook-run",
                    "--state-dir",
                    str(state_dir),
                    "--event",
                    "stop",
                    "--host",
                    "codex",
                    "--json",
                ).stdout
            )
            self.assertEqual(active_after["hooks"], [])

            allowed = json.loads(
                self.run_statem(
                    "hooks",
                    "run",
                    "stop",
                    "--run-id",
                    "hook-run",
                    "--state-dir",
                    str(state_dir),
                    "--host",
                    "codex",
                    "--json",
                ).stdout
            )
            self.assertEqual(allowed["matched_hooks"], 0)
            self.assertEqual(allowed["decision"], "allow")

    def test_stop_hook_can_require_state_specific_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "explicit-autoloop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: explicit-autoloop
initial: start
nodes:
  start:
    prompt: Work.
  execute:
    prompt: Execute.
    state_hooks:
      - name: continue_execute
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
  review:
    prompt: Review.
    state_hooks:
      - name: continue_review
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
  handoff:
    prompt: Handoff.
edges:
  - from: start
    to: execute
  - from: execute
    to: review
  - from: review
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem("start", str(spec), "--run-id", "explicit-run", "--state-dir", str(state_dir), "--json")
            env = {"STATEM_STOP_REQUIRE_STATE_HOOKS": "true"}
            host_payload = {
                "cwd": str(root),
                "session_id": "entry-scoped-test",
                "stop_hook_active": False,
            }
            start_stop = self.run_stop_hook(host_payload, env=env)
            self.assertEqual(start_stop.stdout, "")

            self.run_statem("goto", "execute", "--run-id", "explicit-run", "--state-dir", str(state_dir), "--json")
            execute_stop = self.run_stop_hook(host_payload, env=env)
            payload = json.loads(execute_stop.stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("State hook: continue_execute", payload["reason"])

            same_entry = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            payload = json.loads(same_entry.stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("State hook: continue_execute", payload["reason"])

            exhausted_entry = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            self.assertEqual(exhausted_entry.stdout, "")

            self.run_statem("goto", "review", "--run-id", "explicit-run", "--state-dir", str(state_dir), "--json")
            next_entry = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            payload = json.loads(next_entry.stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("State hook: continue_review", payload["reason"])

            same_review_entry = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            payload = json.loads(same_review_entry.stdout)
            self.assertEqual(payload["decision"], "block")

            exhausted_review_entry = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            self.assertEqual(exhausted_review_entry.stdout, "")

    def test_stop_hook_entry_continuation_budget_is_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "explicit-autoloop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: explicit-autoloop
initial: execute
nodes:
  execute:
    prompt: Execute.
    state_hooks:
      - name: continue_execute
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
  handoff:
    prompt: Handoff.
edges:
  - from: execute
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "budget-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            env = {
                "STATEM_STOP_REQUIRE_STATE_HOOKS": "true",
                "STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY": "1",
            }
            host_payload = {
                "cwd": str(root),
                "session_id": "budget-test",
                "stop_hook_active": False,
            }
            first = self.run_stop_hook(host_payload, env=env)
            self.assertEqual(json.loads(first.stdout)["decision"], "block")
            exhausted = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            self.assertEqual(exhausted.stdout, "")

    def test_stop_hook_reserves_one_extra_slot_after_current_entry_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "blocked-transition-autoloop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: blocked-transition-autoloop
initial: execute
nodes:
  execute:
    prompt: Execute.
    state_hooks:
      - name: continue_execute
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
  handoff:
    prompt: Handoff.
edges:
  - from: execute
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "blocked-budget-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            env = {
                "STATEM_STOP_REQUIRE_STATE_HOOKS": "true",
                "STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY": "1",
                "STATEM_STOP_EXTRA_CONTINUATIONS_AFTER_GOTO_BLOCKED": "1",
            }
            host_payload = {
                "cwd": str(root),
                "session_id": "blocked-budget-test",
                "stop_hook_active": False,
            }
            first = self.run_stop_hook(host_payload, env=env)
            self.assertEqual(json.loads(first.stdout)["decision"], "block")

            state_path = (
                state_dir / "runs" / "blocked-budget-run" / "state.json"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["history"].append(
                {
                    "event": "goto_blocked",
                    "current_entry_id": state["current_entry_id"],
                    "from": "execute",
                    "to": "handoff",
                }
            )
            state_path.write_text(
                json.dumps(state, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            repair_slot = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            repair_payload = json.loads(repair_slot.stdout)
            self.assertEqual(repair_payload["decision"], "block")
            self.assertIn(
                "Blocked transition repair continuation",
                repair_payload["reason"],
            )

            exhausted = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            self.assertEqual(exhausted.stdout, "")

    def test_stop_hook_does_not_apply_blocked_slot_to_another_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "other-entry-autoloop.yaml"
            state_dir = root / ".statem"
            spec.write_text(
                """
name: other-entry-autoloop
initial: execute
nodes:
  execute:
    prompt: Execute.
    state_hooks:
      - name: continue_execute
        event: stop
        host: codex
        template: statem_autoloop
        scope: current_entry
  handoff:
    prompt: Handoff.
edges:
  - from: execute
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem(
                "start",
                str(spec),
                "--run-id",
                "other-entry-run",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            env = {
                "STATEM_STOP_REQUIRE_STATE_HOOKS": "true",
                "STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY": "1",
                "STATEM_STOP_EXTRA_CONTINUATIONS_AFTER_GOTO_BLOCKED": "1",
            }
            host_payload = {
                "cwd": str(root),
                "session_id": "other-entry-test",
                "stop_hook_active": False,
            }
            first = self.run_stop_hook(host_payload, env=env)
            self.assertEqual(json.loads(first.stdout)["decision"], "block")

            state_path = state_dir / "runs" / "other-entry-run" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["history"].append(
                {
                    "event": "goto_blocked",
                    "current_entry_id": "another-entry",
                    "from": "execute",
                    "to": "handoff",
                }
            )
            state_path.write_text(
                json.dumps(state, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            exhausted = self.run_stop_hook(
                {**host_payload, "stop_hook_active": True}, env=env
            )
            self.assertEqual(exhausted.stdout, "")

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

    def test_teamrun_required_node_blocks_until_decided(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "team.yaml"
            state_dir = root / ".statem"
            tasks = root / "tasks.json"
            result = root / "result.json"
            spec.write_text(
                """
name: team-demo
initial: search
nodes:
  search:
    prompt: Search in parallel.
    multi_agent:
      mode: fanout_search_reduce
      max_parallel: 1
      required: true
      reducer:
        strategy: highest-confidence
        candidate_field: answer
        confidence_field: confidence
  handoff:
    prompt: Done.
edges:
  - from: search
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            tasks.write_text(
                json.dumps({"tasks": [{"task_id": "a", "priority": 1, "input": {"range": [0, 10]}}]}),
                encoding="utf-8",
            )
            result.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "answer found",
                        "claims": [{"answer": 7, "confidence": 0.8, "evidence_refs": ["scratch://a"]}],
                        "evidence": [],
                        "coverage": {"complete": True},
                        "children": [],
                        "prune_proposals": [],
                    }
                ),
                encoding="utf-8",
            )

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", "team-run", "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            cur = json.loads(self.run_statem("cur", "--run-id", "team-run", "--state-dir", str(state_dir), "--json").stdout)
            self.assertEqual(cur["multi_agent"]["mode"], "fanout_search_reduce")

            blocked = self.run_statem(
                "goto",
                "handoff",
                "--run-id",
                "team-run",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(blocked.stdout)
            self.assertEqual(blocked_payload["details"]["stage"], "multi_agent")

            self.run_statem("team", "init", str(tasks), "--run-id", "team-run", "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            claim = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    "team-run",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-a",
                    "--json",
                ).stdout
            )
            self.assertEqual(claim["claimed_task"]["task_id"], "a")
            self.run_statem(
                "team",
                "submit",
                "a",
                str(result),
                "--run-id",
                "team-run",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--agent-id",
                "worker-a",
                "--json",
            )
            self.run_statem("team", "advance", "reducing", "--run-id", "team-run", "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            reduced = json.loads(
                self.run_statem(
                    "team",
                    "reduce",
                    "--run-id",
                    "team-run",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "lead",
                    "--json",
                ).stdout
            )
            self.assertEqual(reduced["decision"]["status"], "decided")

            moved = json.loads(
                self.run_statem("goto", "handoff", "--run-id", "team-run", "--state-dir", str(state_dir), "--json").stdout
            )
            self.assertEqual(moved["current"], "handoff")

    def test_teamrun_all_claims_table_blocks_empty_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "team-empty-claims.yaml"
            state_dir = root / ".statem"
            tasks = root / "tasks.json"
            result = root / "empty-result.json"
            spec.write_text(
                """
name: team-empty-claims
initial: search
nodes:
  search:
    prompt: Search in parallel.
    multi_agent:
      mode: fanout_search_reduce
      max_parallel: 1
      required: true
      reducer:
        strategy: all-claims-table
  handoff:
    prompt: Done.
edges:
  - from: search
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            tasks.write_text(
                json.dumps({"tasks": [{"task_id": "a", "priority": 1, "input": {"range": [0, 10]}}]}),
                encoding="utf-8",
            )
            result.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "searched but put conclusions only in evidence",
                        "claims": [],
                        "evidence": [{"type": "note", "text": "candidate described here"}],
                        "coverage": {"complete": True},
                        "children": [],
                        "prune_proposals": [],
                    }
                ),
                encoding="utf-8",
            )

            start = json.loads(
                self.run_statem(
                    "start",
                    str(spec),
                    "--run-id",
                    "team-empty-claims",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            entry = start["current_entry_id"]
            self.run_statem(
                "team",
                "init",
                str(tasks),
                "--run-id",
                "team-empty-claims",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--json",
            )
            self.run_statem(
                "team",
                "claim",
                "--run-id",
                "team-empty-claims",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--agent-id",
                "worker-a",
                "--json",
            )
            self.run_statem(
                "team",
                "submit",
                "a",
                str(result),
                "--run-id",
                "team-empty-claims",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--agent-id",
                "worker-a",
                "--json",
            )
            self.run_statem(
                "team",
                "advance",
                "reducing",
                "--run-id",
                "team-empty-claims",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--json",
            )
            reduced = json.loads(
                self.run_statem(
                    "team",
                    "reduce",
                    "--run-id",
                    "team-empty-claims",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "lead",
                    "--json",
                ).stdout
            )
            self.assertEqual(reduced["phase"], "blocked")
            self.assertEqual(reduced["decision"]["status"], "blocked")
            self.assertEqual(reduced["decision"]["answer"], "0 claim(s) collected")

    def test_teamrun_report_is_append_only_and_reducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "team-report.yaml"
            state_dir = root / ".statem"
            tasks = root / "tasks.json"
            report = root / "report.json"
            result = root / "result.json"
            spec.write_text(
                """
name: team-report
initial: search
nodes:
  search:
    prompt: Search in parallel.
    multi_agent:
      mode: fanout_search_reduce
      max_parallel: 1
      required: true
      reducer:
        strategy: highest-confidence
        candidate_field: answer
        confidence_field: confidence
  handoff:
    prompt: Done.
edges:
  - from: search
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            tasks.write_text(
                json.dumps({"tasks": [{"task_id": "a", "priority": 1, "input": {"range": [0, 10]}}]}),
                encoding="utf-8",
            )
            report.write_text(
                json.dumps(
                    {
                        "status": "progress",
                        "summary": "candidate seen during exploration",
                        "claims": [{"answer": 7, "confidence": 0.7, "evidence_refs": ["scratch://report"]}],
                        "evidence": [{"type": "partial_trace"}],
                        "coverage": {"complete": False},
                    }
                ),
                encoding="utf-8",
            )
            result.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "final result closed the task",
                        "claims": [],
                        "evidence": [],
                        "coverage": {"complete": True},
                        "children": [],
                        "prune_proposals": [],
                    }
                ),
                encoding="utf-8",
            )

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", "team-report", "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", "team-report", "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            claim = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    "team-report",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-a",
                    "--json",
                ).stdout
            )
            self.assertIn("/work/worker-a", claim["claimed_task"]["work_dir"])
            reported = json.loads(
                self.run_statem(
                    "team",
                    "report",
                    "a",
                    str(report),
                    "--run-id",
                    "team-report",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-a",
                    "--json",
                ).stdout
            )
            self.assertEqual(reported["reported_task"]["claims"], 1)
            self.assertEqual(reported["counts"]["leased"], 1)
            collected = json.loads(
                self.run_statem(
                    "team",
                    "collect",
                    "--run-id",
                    "team-report",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--json",
                ).stdout
            )
            self.assertEqual(len(collected["reports"]), 1)
            self.assertEqual(collected["reports"][0]["claims"], 1)

            self.run_statem(
                "team",
                "submit",
                "a",
                str(result),
                "--run-id",
                "team-report",
                "--state-dir",
                str(state_dir),
                "--entry-id",
                entry,
                "--agent-id",
                "worker-a",
                "--json",
            )
            self.run_statem("team", "advance", "reducing", "--run-id", "team-report", "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            reduced = json.loads(
                self.run_statem(
                    "team",
                    "reduce",
                    "--run-id",
                    "team-report",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "lead",
                    "--json",
                ).stdout
            )
            self.assertEqual(reduced["decision"]["answer"]["answer"], 7)
            self.assertEqual(reduced["decision"]["selected_claim"]["_source"], "report")

    def test_teamrun_claims_are_manifest_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "team-race.yaml"
            state_dir = root / ".statem"
            tasks = root / "tasks.json"
            spec.write_text(
                """
name: team-race
initial: search
nodes:
  search:
    prompt: Search in parallel.
    multi_agent:
      mode: fanout_search_reduce
      max_parallel: 2
      required: true
  handoff:
    prompt: Done.
edges:
  - from: search
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            tasks.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"task_id": "a", "priority": 3, "input": {"range": [0, 9]}},
                            {"task_id": "b", "priority": 2, "input": {"range": [10, 19]}},
                            {"task_id": "c", "priority": 1, "input": {"range": [20, 29]}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", "team-race", "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", "team-race", "--state-dir", str(state_dir), "--entry-id", entry, "--json")

            def claim(worker: int) -> dict[str, object]:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "statem",
                        "team",
                        "claim",
                        "--run-id",
                        "team-race",
                        "--state-dir",
                        str(state_dir),
                        "--entry-id",
                        entry,
                        "--agent-id",
                        f"worker-{worker}",
                        "--json",
                    ],
                    cwd=REPO,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                payload = json.loads(completed.stdout)
                task_id = (payload.get("claimed_task") or {}).get("task_id")
                return {"returncode": completed.returncode, "task_id": task_id, "payload": payload}

            with ThreadPoolExecutor(max_workers=6) as pool:
                claims = list(pool.map(claim, range(6)))

            claimed_ids = [claim["task_id"] for claim in claims if claim["task_id"]]
            self.assertEqual(len(claimed_ids), 2, claims)
            self.assertEqual(len(set(claimed_ids)), 2, claims)

            status = json.loads(
                self.run_statem("team", "status", "--run-id", "team-race", "--state-dir", str(state_dir), "--entry-id", entry, "--json").stdout
            )
            self.assertEqual(status["counts"]["leased"], 2)
            self.assertEqual(status["counts"]["open"], 1)

    def test_teamrun_sharded_claim_uses_ordered_mod_then_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            spec = root / "team-shard.yaml"
            state_dir = root / ".statem"
            tasks = root / "tasks.json"
            spec.write_text(
                """
name: team-shard
initial: search
nodes:
  search:
    prompt: Search in parallel.
    multi_agent:
      mode: fanout_search_reduce
      max_parallel: 4
      required: true
  handoff:
    prompt: Done.
edges:
  - from: search
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )
            tasks.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"task_id": "a", "priority": 4, "input": {"range": [0, 9]}},
                            {"task_id": "b", "priority": 3, "input": {"range": [10, 19]}},
                            {"task_id": "c", "priority": 2, "input": {"range": [20, 29]}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", "team-shard", "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", "team-shard", "--state-dir", str(state_dir), "--entry-id", entry, "--json")

            first = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    "team-shard",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-0",
                    "--worker-index",
                    "0",
                    "--worker-count",
                    "2",
                    "--json",
                ).stdout
            )
            second = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    "team-shard",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-1",
                    "--worker-index",
                    "1",
                    "--worker-count",
                    "2",
                    "--json",
                ).stdout
            )
            third = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    "team-shard",
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-2",
                    "--worker-index",
                    "1",
                    "--worker-count",
                    "2",
                    "--json",
                ).stdout
            )
            self.assertEqual(first["claimed_task"]["task_id"], "a")
            self.assertEqual(second["claimed_task"]["task_id"], "b")
            self.assertEqual(third["claimed_task"]["task_id"], "c")

    def test_teamrun_release_returns_leased_tasks_to_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / ".statem"
            spec = REPO / "examples/teamrun-video-search/runbook.yaml"
            tasks = REPO / "examples/teamrun-video-search/tasks.json"
            run_id = "video-release-test"

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", run_id, "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            claimed = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-a",
                    "--json",
                ).stdout
            )
            task_id = claimed["claimed_task"]["task_id"]
            released = json.loads(
                self.run_statem(
                    "team",
                    "release",
                    task_id,
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-a",
                    "--reason",
                    "launcher_failed",
                    "--json",
                ).stdout
            )
            self.assertEqual(released["counts"]["leased"], 0)
            self.assertEqual(released["counts"]["open"], 3)
            self.assertEqual(released["released"][0]["task_id"], task_id)
            no_op_release = json.loads(
                self.run_statem(
                    "team",
                    "release",
                    "--all-leased",
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--reason",
                    "lease_already_open",
                    "--json",
                ).stdout
            )
            self.assertEqual(no_op_release["counts"]["leased"], 0)
            self.assertEqual(no_op_release["counts"]["open"], 3)
            self.assertEqual(no_op_release["released"], [])
            reclaimed = json.loads(
                self.run_statem(
                    "team",
                    "claim",
                    task_id,
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--agent-id",
                    "worker-b",
                    "--json",
                ).stdout
            )
            self.assertEqual(reclaimed["claimed_task"]["task_id"], task_id)

    def test_teamrun_video_example_worker_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / ".statem"
            spec = REPO / "examples/teamrun-video-search/runbook.yaml"
            tasks = REPO / "examples/teamrun-video-search/tasks.json"
            worker = REPO / "examples/teamrun-video-search/fake_video_worker.py"
            runner = REPO / "integrations/teamrun/teamrun_worker_loop.py"
            run_id = "video-demo-test"

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", run_id, "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--worker-command",
                    f"{sys.executable} {worker}",
                    "--max-workers",
                    "2",
                    "--max-rounds",
                    "3",
                    "--json",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["claimed"], 3)
            self.assertEqual(summary["submitted"], 3)

            self.run_statem("team", "advance", "reducing", "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            reduced = json.loads(
                self.run_statem("team", "reduce", "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--agent-id", "lead", "--json").stdout
            )
            self.assertEqual(reduced["decision"]["answer"]["candidate_frame"], 1375)
            moved = json.loads(
                self.run_statem("goto", "handoff", "--run-id", run_id, "--state-dir", str(state_dir), "--yes", "--json").stdout
            )
            self.assertEqual(moved["current"], "handoff")

    def test_nested_runbook_returns_to_same_parent_entry_without_repeating_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            child = root / "child.yaml"
            parent = root / "parent.yaml"
            child.write_text(
                """
name: child
initial: work
nodes:
  work:
    prompt: Complete the focused family procedure.
  done:
    prompt: Return to the caller.
edges:
  - from: work
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            parent.write_text(
                """
name: parent
initial: solve
nodes:
  solve:
    in_hook:
      - type: runbook
        runbook: child.yaml
        return_states:
          - done
        role: family-reviewer
      - type: command
        run: printf ready >> parent-ready.txt
  handoff:
    prompt: Finished.
edges:
  - from: solve
    to: handoff
""".strip()
                + "\n",
                encoding="utf-8",
            )

            validated = json.loads(
                self.run_statem("validate", str(parent), "--strict", "--json").stdout
            )
            self.assertTrue(validated["ok"])
            started = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "nested",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(started["spec_name"], "child")
            self.assertEqual(started["current"], "work")
            self.assertEqual(started["runbook_depth"], 1)
            parent_entry = started["runbook_stack"][0]["parent_entry_id"]
            self.assertFalse((root / "parent-ready.txt").exists())

            resumed = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "nested",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(resumed["spec_name"], "child")
            self.assertEqual(resumed["runbook_depth"], 1)
            prompt_payload = json.loads(
                self.run_statem(
                    "prompt",
                    "--run-id",
                    "nested",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(prompt_payload["spec"], str(parent.resolve()))
            self.assertEqual(prompt_payload["active_spec"], str(child.resolve()))
            self.assertIn("statem return", prompt_payload["prompt"])

            blocked = self.run_statem(
                "return",
                "--run-id",
                "nested",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(json.loads(blocked.stdout)["details"]["allowed_return_states"], ["done"])

            self.run_statem(
                "goto",
                "done",
                "--run-id",
                "nested",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            returned = json.loads(
                self.run_statem(
                    "return",
                    "--run-id",
                    "nested",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(returned["spec_name"], "parent")
            self.assertEqual(returned["current"], "solve")
            self.assertEqual(returned["current_entry_id"], parent_entry)
            self.assertEqual(returned["runbook_depth"], 0)
            self.assertEqual((root / "parent-ready.txt").read_text(encoding="utf-8"), "ready")

            resumed_parent = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "nested",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(resumed_parent["runbook_depth"], 0)
            self.assertEqual((root / "parent-ready.txt").read_text(encoding="utf-8"), "readyready")
            state = json.loads(
                (state_dir / "runs" / "nested" / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(state["runbook_call_receipts"]), 1)

    def test_nested_runbook_before_transfer_resumes_same_edge_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            child = root / "gate.yaml"
            parent = root / "parent.yaml"
            child.write_text(
                """
name: transfer-gate
initial: inspect
nodes:
  inspect: Inspect the family-specific boundary.
  accepted: Return to the transfer.
edges:
  - from: inspect
    to: accepted
""".strip()
                + "\n",
                encoding="utf-8",
            )
            parent.write_text(
                """
name: parent-transfer
initial: solve
nodes:
  solve:
    before_transfer:
      - type: runbook
        runbook: gate.yaml
        return_states:
          - accepted
      - type: command
        run: printf checked >> transfer.log
  done: Done.
edges:
  - from: solve
    to: done
    max_attempts: 1
""".strip()
                + "\n",
                encoding="utf-8",
            )

            self.run_statem(
                "start",
                str(parent),
                "--run-id",
                "transfer",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            entered = json.loads(
                self.run_statem(
                    "goto",
                    "done",
                    "--run-id",
                    "transfer",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(entered["spec_name"], "transfer-gate")
            self.assertEqual(entered["current"], "inspect")
            self.run_statem(
                "goto",
                "accepted",
                "--run-id",
                "transfer",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            returned = json.loads(
                self.run_statem(
                    "return",
                    "--run-id",
                    "transfer",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(returned["from"], "solve")
            self.assertEqual(returned["to"], "done")
            self.assertEqual((root / "transfer.log").read_text(encoding="utf-8"), "checked")
            state = json.loads(
                (state_dir / "runs" / "transfer" / "state.json").read_text(encoding="utf-8")
            )
            attempts = state["edge_attempts"]
            parent_entry = next(iter(attempts))
            self.assertEqual(attempts[parent_entry]["solve"]["done"], 1)

    def test_nested_runbook_selector_can_skip_or_route_without_loading_all_practices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            selector = root / "route.json"
            child = root / "family.yaml"
            parent = root / "parent.yaml"
            child.write_text(
                """
name: family-procedure
initial: inspect
nodes:
  inspect: Run only the selected family procedure.
  done: Return.
edges:
  - from: inspect
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            parent.write_text(
                """
name: routed-parent
initial: solve
nodes:
  solve:
    in_hook:
      - type: runbook
        selector:
          path: route.json
          json_path: family
        routes:
          boundary: family.yaml
        default: skip
        return_states:
          - done
      - type: command
        run: printf thin >> thin.log
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.assertTrue(
                json.loads(
                    self.run_statem("validate", str(parent), "--strict", "--json").stdout
                )["ok"]
            )

            selector.write_text('{"family":"ordinary"}\n', encoding="utf-8")
            skipped = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "skip",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(skipped["spec_name"], "routed-parent")
            self.assertEqual(skipped["runbook_depth"], 0)
            self.assertEqual((root / "thin.log").read_text(encoding="utf-8"), "thin")

            selector.write_text('{"family":"boundary"}\n', encoding="utf-8")
            stable_skip = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "skip",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(stable_skip["spec_name"], "routed-parent")
            self.assertEqual(stable_skip["runbook_depth"], 0)
            self.assertEqual((root / "thin.log").read_text(encoding="utf-8"), "thinthin")

            routed = json.loads(
                self.run_statem(
                    "start",
                    str(parent),
                    "--run-id",
                    "route",
                    "--state-dir",
                    str(state_dir),
                    "--json",
                ).stdout
            )
            self.assertEqual(routed["spec_name"], "family-procedure")
            self.assertEqual(routed["runbook_depth"], 1)
            self.assertFalse(routed["runbook_return"]["can_return"])

    def test_nested_runbook_source_binding_and_hook_order_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            child = root / "child.yaml"
            parent = root / "parent.yaml"
            child.write_text(
                """
name: child
initial: work
nodes:
  work: Work.
  done:
    prompt: Done.
    out_hook:
      type: command
      run: printf exited >> child-exit.log
edges:
  - from: work
    to: done
""".strip()
                + "\n",
                encoding="utf-8",
            )
            parent.write_text(
                """
name: invalid-parent
initial: solve
nodes:
  solve:
    in_hook:
      - type: message
        text: This side effect would precede the call.
      - type: runbook
        runbook: child.yaml
        return_states:
          - done
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )
            invalid = self.run_statem("validate", str(parent), "--json", check=False)
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("must be the first hook item", json.loads(invalid.stdout)["error"])

            parent.write_text(
                """
name: bound-parent
initial: solve
nodes:
  solve:
    in_hook:
      type: runbook
      runbook: child.yaml
      return_states:
        - done
edges: []
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.run_statem(
                "start",
                str(parent),
                "--run-id",
                "bound",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            child_source = child.read_text(encoding="utf-8")
            child.write_text(child_source + "# drift\n", encoding="utf-8")
            blocked = self.run_statem(
                "cur",
                "--run-id",
                "bound",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("source changed", json.loads(blocked.stdout)["error"])

            child.write_text(child_source, encoding="utf-8")
            self.run_statem(
                "start",
                str(parent),
                "--run-id",
                "parent-bound",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            parent.write_text(parent.read_text(encoding="utf-8") + "# parent drift\n", encoding="utf-8")
            self.run_statem(
                "goto",
                "done",
                "--run-id",
                "parent-bound",
                "--state-dir",
                str(state_dir),
                "--json",
            )
            parent_blocked = self.run_statem(
                "return",
                "--run-id",
                "parent-bound",
                "--state-dir",
                str(state_dir),
                "--json",
                check=False,
            )
            self.assertEqual(parent_blocked.returncode, 2)
            self.assertIn("Parent runbook source changed", json.loads(parent_blocked.stdout)["error"])
            self.assertFalse((root / "child-exit.log").exists())

    def test_teamrun_worker_loop_wall_timeout_bounds_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            spec = REPO / "examples/teamrun-video-search/runbook.yaml"
            tasks = REPO / "examples/teamrun-video-search/tasks.json"
            runner = REPO / "integrations/teamrun/teamrun_worker_loop.py"
            slow_worker = root / "slow_worker.py"
            slow_worker.write_text(
                """
import json
import os
import time
from pathlib import Path

time.sleep(5)
Path(os.environ["STATEM_TEAM_RESULT_FILE"]).write_text(json.dumps({
    "status": "completed",
    "summary": "too late",
    "claims": [{"candidate_frame": 1, "confidence": 0.1}],
    "evidence": [],
    "coverage": {"complete": True},
    "children": [],
    "prune_proposals": [],
}) + "\\n", encoding="utf-8")
""".lstrip(),
                encoding="utf-8",
            )
            run_id = "video-wall-timeout-test"

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", run_id, "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")

            before = time.monotonic()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--worker-command",
                    f"{sys.executable} {slow_worker}",
                    "--max-workers",
                    "2",
                    "--max-rounds",
                    "1",
                    "--timeout",
                    "10",
                    "--wall-timeout",
                    "0.5",
                    "--json",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            elapsed = time.monotonic() - before
            self.assertLess(elapsed, 3.0, completed.stderr + completed.stdout)
            self.assertEqual(completed.returncode, 1)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary["timed_out"])
            self.assertEqual(summary["claimed"], 2)
            self.assertEqual(summary["submitted"], 2)

    def test_teamrun_codex_workers_launch_scoped_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / ".statem"
            spec = REPO / "examples/teamrun-video-search/runbook.yaml"
            tasks = REPO / "examples/teamrun-video-search/tasks.json"
            runner = REPO / "integrations/teamrun/teamrun_codex_workers.py"
            fake_codex = root / "fake_codex.py"
            fake_codex.write_text(
                """
from __future__ import annotations

import json
import os
from pathlib import Path

assignment = json.loads(Path(os.environ["STATEM_TEAM_ASSIGNMENT_FILE"]).read_text(encoding="utf-8"))
result_path = Path(os.environ["STATEM_TEAM_RESULT_FILE"])
report_path = Path(os.environ["STATEM_TEAM_REPORT_FILE"])
task_id = str(assignment["task_id"])
data = assignment["assignment"]["input"]
start = int(data["start_frame"])
end = int(data["end_frame"])
takeoff = int(data["takeoff_frame"])
claims = []
evidence = [{
    "type": "fake_codex",
    "task_id": task_id,
    "frame_range": [start, end],
    "return_deadline": os.environ.get("STATEM_TEAM_RETURN_DEADLINE"),
    "return_deadline_epoch": os.environ.get("STATEM_TEAM_RETURN_DEADLINE_EPOCH"),
    "return_slack": os.environ.get("STATEM_TEAM_RETURN_SLACK_SECONDS"),
    "work_dir": os.environ.get("STATEM_TEAM_WORK_DIR"),
}]
report = {
    "status": "progress",
    "summary": f"scanned frames {start}-{end}",
    "claims": claims,
    "evidence": evidence,
    "coverage": {"complete": False, "frame_range": [start, end]},
}
status = "completed"
summary = f"no takeoff candidate in frames {start}-{end}"
if start <= takeoff <= end:
    status = "terminal"
    summary = f"candidate takeoff frame {takeoff}"
    claims.append({
        "claim": "earliest sustained wheel separation in assigned segment",
        "candidate_frame": takeoff,
        "confidence": 0.93,
        "evidence_refs": [f"frame://demo-flight/{takeoff}"],
    })
    report["claims"] = claims
    report["summary"] = summary
result = {
    "status": status,
    "summary": summary,
    "claims": claims,
    "evidence": evidence,
    "coverage": {"complete": True, "frame_range": [start, end]},
    "children": [],
    "prune_proposals": [],
}
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
print("fake codex wrote", result_path, "and", report_path)
""".lstrip(),
                encoding="utf-8",
            )
            run_id = "video-codex-team-test"

            start = json.loads(
                self.run_statem("start", str(spec), "--run-id", run_id, "--state-dir", str(state_dir), "--json").stdout
            )
            entry = start["current_entry_id"]
            self.run_statem("team", "init", str(tasks), "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--codex-command",
                    f"{sys.executable} {fake_codex}",
                    "--model",
                    "fake",
                    "--reasoning-effort",
                    "low",
                    "--max-workers",
                    "2",
                    "--max-rounds",
                    "3",
                    "--timeout",
                    "10",
                    "--return-slack",
                    "3",
                    "--json",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["claimed"], 3)
            self.assertEqual(summary["reported"], 3)
            self.assertEqual(summary["report_errors"], 0)
            self.assertEqual(summary["submitted"], 3)
            self.assertEqual(summary["failed"], 0)
            reducer_input = json.loads(
                self.run_statem(
                    "team",
                    "reduce-input",
                    "--run-id",
                    run_id,
                    "--state-dir",
                    str(state_dir),
                    "--entry-id",
                    entry,
                    "--json",
                ).stdout
            )["reduce_input"]
            evidence_items = [
                evidence
                for task_entry in reducer_input["tasks"]
                for result in task_entry["results"]
                for evidence in result.get("evidence", [])
            ]
            report_items = [
                report
                for task_entry in reducer_input["tasks"]
                for report in task_entry["reports"]
            ]
            self.assertEqual(len(report_items), 3)
            self.assertTrue(all(item.get("return_deadline") for item in evidence_items), evidence_items)
            self.assertTrue(all(item.get("return_deadline_epoch") for item in evidence_items), evidence_items)
            self.assertTrue(all(item.get("return_slack") == "3.000" for item in evidence_items), evidence_items)

            self.run_statem("team", "advance", "reducing", "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--json")
            reduced = json.loads(
                self.run_statem("team", "reduce", "--run-id", run_id, "--state-dir", str(state_dir), "--entry-id", entry, "--agent-id", "lead", "--json").stdout
            )
            self.assertEqual(reduced["decision"]["answer"]["candidate_frame"], 1375)


if __name__ == "__main__":
    unittest.main()
