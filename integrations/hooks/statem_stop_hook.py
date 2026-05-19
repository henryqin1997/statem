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
from typing import Any


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

    statem_cmd = os.environ.get("STATEM_COMMAND", f"{sys.executable} -m statem")
    cur = _run_statem_json(statem_cmd, cwd, state_dir, "cur")
    if cur is None:
        return _allow(
            system_message="statem Stop hook found an active run but could not read it; allowing stop."
        )

    current = str(cur.get("current") or "")
    stop_states = _stop_states()
    next_states = cur.get("next") or []
    if current in stop_states or not next_states:
        return _allow()

    reason = _continuation_reason(statem_cmd, state_dir, current, next_states)
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


def _run_statem_json(statem_cmd: str, cwd: Path, state_dir: Path, command: str) -> dict[str, Any] | None:
    try:
        argv = [*shlex.split(statem_cmd), command, "--state-dir", str(state_dir), "--json"]
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


def _continuation_reason(statem_cmd: str, state_dir: Path, current: str, next_states: list[Any]) -> str:
    next_names = ", ".join(str(edge.get("to")) for edge in next_states if isinstance(edge, dict)) or "(none)"
    return "\n".join(
        [
            "Continue the active statem-managed run instead of stopping.",
            "",
            "First inspect durable state:",
            f"{statem_cmd} cur --state-dir {sh_quote(str(state_dir))} --json",
            f"{statem_cmd} next --state-dir {sh_quote(str(state_dir))} --json",
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
    return "'" + value.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
