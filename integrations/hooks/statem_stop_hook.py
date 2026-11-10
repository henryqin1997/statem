#!/usr/bin/env python3
"""Host Stop hook adapter for statem-managed runs.

Works with hosts whose Stop hook supports `{"decision": "block", "reason": ...}`
continuations, including Codex and Claude Code. This script intentionally does
not advance statem state. It only nudges the agent to inspect statem and keep
working when a run is active.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


DEFAULT_STOP_STATES = {"handoff", "done", "complete", "completed", "finished"}


def main() -> int:
    payload = _read_payload()
    if payload.get("stop_hook_active") is True:
        return _allow()

    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve()
    state_dir = Path(os.environ.get("STATEM_STATE_DIR", cwd / ".statem")).expanduser()
    if not state_dir.is_absolute():
        state_dir = (cwd / state_dir).resolve()

    if not (state_dir / "active_run").exists():
        return _allow()

    statem_command_text = os.environ.get("STATEM_COMMAND")
    try:
        statem_argv = _statem_command_argv(statem_command_text)
    except ValueError:
        return _allow(
            system_message="statem Stop hook found an invalid STATEM_COMMAND; allowing stop."
        )

    cur = _run_statem_json(statem_argv, cwd, state_dir, "cur")
    if cur is None:
        return _allow(
            system_message="statem Stop hook found an active run but could not read it; allowing stop."
        )

    current = str(cur.get("current") or "")
    stop_states = _stop_states()
    next_states = cur.get("next") or []
    if current in stop_states or not next_states:
        return _allow()

    reason = _continuation_reason(
        statem_argv,
        state_dir,
        current,
        next_states,
        statem_command_text=statem_command_text or f"{sys.executable} -m statem",
    )
    return _continue(reason)


def _read_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def _stop_states() -> set[str]:
    raw = os.environ.get("STATEM_AUTOLOOP_STOP_STATES")
    if not raw:
        return DEFAULT_STOP_STATES
    return {part.strip() for part in raw.split(",") if part.strip()}


def _statem_command_argv(
    command: str | None, *, windows: bool | None = None
) -> list[str]:
    """Return a shell-free argv prefix for invoking statem.

    Keeping the default as separate argv entries avoids reparsing
    ``sys.executable``, which may contain backslashes or spaces on Windows.
    Environment overrides remain strings for compatibility and are parsed with
    the platform's quoting convention.
    """

    if command is None:
        return [sys.executable, "-m", "statem"]

    is_windows = os.name == "nt" if windows is None else windows
    argv = shlex.split(command, posix=not is_windows)
    if is_windows:
        # shlex's non-POSIX mode preserves surrounding quotes. subprocess with
        # shell=False expects the executable path without those quote bytes.
        argv = [_strip_matching_quotes(part) for part in argv]
    if not argv:
        raise ValueError("STATEM_COMMAND must not be empty")
    return argv


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _format_argv(argv: Sequence[str], *, windows: bool | None = None) -> str:
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        return subprocess.list2cmdline(list(argv))
    return shlex.join(argv)


def _run_statem_json(
    statem_argv: Sequence[str], cwd: Path, state_dir: Path, command: str
) -> dict[str, Any] | None:
    try:
        argv = [*statem_argv, command, "--state-dir", str(state_dir), "--json"]
        completed = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _continuation_reason(
    statem_argv: Sequence[str],
    state_dir: Path,
    current: str,
    next_states: list[Any],
    *,
    statem_command_text: str | None = None,
    windows: bool | None = None,
) -> str:
    next_names = ", ".join(str(edge.get("to")) for edge in next_states if isinstance(edge, dict)) or "(none)"
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        cur_command = _format_argv(
            [*statem_argv, "cur", "--state-dir", str(state_dir), "--json"],
            windows=True,
        )
        next_command = _format_argv(
            [*statem_argv, "next", "--state-dir", str(state_dir), "--json"],
            windows=True,
        )
    else:
        # Keep the pre-Windows-fix continuation text byte-for-byte compatible
        # on POSIX, including the caller's STATEM_COMMAND spelling and the
        # always-single-quoted state directory.
        command_text = statem_command_text or _format_argv(statem_argv, windows=False)
        cur_command = f"{command_text} cur --state-dir {sh_quote(str(state_dir))} --json"
        next_command = f"{command_text} next --state-dir {sh_quote(str(state_dir))} --json"
    return "\n".join(
        [
            "Continue the active statem-managed run instead of stopping.",
            "",
            "First inspect durable state:",
            cur_command,
            next_command,
            "",
            f"Current state: {current}",
            f"Allowed next states: {next_names}",
            "",
            "Follow the current node prompt. Move only with `statem goto <next-state>`.",
            "If the current node requires user input or is ready for handoff, explain that and stop.",
        ]
    )


def _allow(*, system_message: str | None = None) -> int:
    if system_message:
        print(json.dumps({"systemMessage": system_message}))
    return 0


def _continue(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def sh_quote(value: str) -> str:
    """Quote one POSIX shell value using the hook's legacy rendering."""

    return "'" + value.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
