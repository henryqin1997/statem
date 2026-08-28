from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from statem.core import RunOptions, StatemRuntime


REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / "integrations" / "hooks" / "statem_stop_hook.py"
HOOK_SPEC = importlib.util.spec_from_file_location("statem_stop_hook", HOOK_PATH)
if HOOK_SPEC is None or HOOK_SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"could not load {HOOK_PATH}")
STOP_HOOK = importlib.util.module_from_spec(HOOK_SPEC)
HOOK_SPEC.loader.exec_module(STOP_HOOK)


class NonInteractiveConfirmationTest(unittest.TestCase):
    def test_manual_check_fails_cleanly_when_tty_reaches_eof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = StatemRuntime(
                RunOptions(state_dir=Path(temp_dir), json_mode=True)
            )
            fake_stdin = mock.Mock()
            fake_stdin.isatty.return_value = True
            with mock.patch("statem.core.sys.stdin", fake_stdin), mock.patch(
                "builtins.input", side_effect=EOFError
            ):
                result = runtime._run_manual(
                    {"type": "manual", "prompt": "Confirm release"}, "condition"
                )

        self.assertFalse(result["passed"])
        self.assertEqual(
            result["output"],
            "confirmation required (EOF); rerun with --yes to auto-confirm",
        )

    def test_checklist_fails_cleanly_when_tty_reaches_eof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = StatemRuntime(
                RunOptions(state_dir=Path(temp_dir), json_mode=True)
            )
            fake_stdin = mock.Mock()
            fake_stdin.isatty.return_value = True
            with mock.patch("statem.core.sys.stdin", fake_stdin), mock.patch(
                "builtins.input", side_effect=EOFError
            ):
                result = runtime._run_checklist(
                    {"type": "checklist", "items": ["tests passed"]},
                    "before_transfer",
                )

        self.assertFalse(result["passed"])
        self.assertEqual(
            result["output"],
            "unchecked (EOF): tests passed; rerun with --yes to auto-confirm",
        )


class WindowsStopHookCommandTest(unittest.TestCase):
    def test_windows_parser_preserves_backslashes(self) -> None:
        command = r"D:\venv\Scripts\python.exe -m statem"
        self.assertEqual(
            STOP_HOOK._statem_command_argv(command, windows=True),
            [r"D:\venv\Scripts\python.exe", "-m", "statem"],
        )

    def test_windows_parser_removes_quotes_around_path_with_spaces(self) -> None:
        command = r'"C:\Program Files\Python311\python.exe" -m statem'
        self.assertEqual(
            STOP_HOOK._statem_command_argv(command, windows=True),
            [r"C:\Program Files\Python311\python.exe", "-m", "statem"],
        )

    def test_default_command_keeps_executable_as_one_argv_entry(self) -> None:
        executable = r"C:\Program Files\Python311\python.exe"
        with mock.patch.object(STOP_HOOK.sys, "executable", executable):
            self.assertEqual(
                STOP_HOOK._statem_command_argv(None),
                [executable, "-m", "statem"],
            )

    def test_statem_runner_does_not_reparse_command_prefix(self) -> None:
        prefix = [r"D:\venv\Scripts\python.exe", "-m", "statem"]
        completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with mock.patch.object(
            STOP_HOOK.subprocess, "run", return_value=completed
        ) as run:
            result = STOP_HOOK._run_statem_json(
                prefix, Path(r"D:\work"), Path(r"D:\work\.statem"), "cur"
            )

        self.assertEqual(result, {})
        self.assertEqual(
            run.call_args.args[0],
            [
                r"D:\venv\Scripts\python.exe",
                "-m",
                "statem",
                "cur",
                "--state-dir",
                r"D:\work\.statem",
                "--json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
