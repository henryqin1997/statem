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

    def test_validate_strict_rejects_unknown_and_misplaced_keywords(self) -> None:
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
    next:
      - to: done
        max_atempts: 2
        condition:
          type: command
          run: "true"
          timout: 1
  done: Done.
  finish: Finish.
edges:
  - from: done
    to: finish
    before_transfer:
      type: predicate
      path: misplaced.txt
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
                "max_atempts",
                "before_transfer",
                "timout",
            ):
                self.assertIn(keyword, error)
            self.assertIn("did you mean 'before_transfer'?", error)
            self.assertIn("did you mean 'max_attempts'?", error)

    def test_validate_strict_accepts_supported_nested_keywords(self) -> None:
        validated = self.run_statem("validate", "examples/coding-agent.yaml", "--strict", "--json")
        payload = json.loads(validated.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["strict"])

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
            self.assertIn("not allowed", json.loads(rejected_write.stdout)["error"])

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
