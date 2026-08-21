#!/usr/bin/env python3
"""Host Stop hook adapter for statem-managed runs.

Works with hosts whose Stop hook supports `{"decision": "block", "reason": ...}`
continuations, including Codex and Claude Code. This script intentionally does
not advance statem state. It only nudges the agent to inspect statem and keep
working when a run is active.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_STOP_STATES = {"handoff", "done", "complete", "completed", "finished"}
DEFAULT_ENTRY_CONTINUATION_BUDGET = 2


def main() -> int:
    payload = _read_payload()
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve()
    state_dir = Path(os.environ.get("STATEM_STATE_DIR", cwd / ".statem")).expanduser()
    if not state_dir.is_absolute():
        state_dir = (cwd / state_dir).resolve()

    if not (state_dir / "active_run").exists():
        return _allow()

    statem_cmd = os.environ.get("STATEM_COMMAND", f"{sys.executable} -m statem")
    host = os.environ.get("STATEM_HOST", "").strip()
    hook_args = ["hooks", "run", "stop", "--command", statem_cmd]
    if host:
        hook_args.extend(["--host", host])
    hook_payload = _run_statem_json(
        statem_cmd,
        cwd,
        state_dir,
        *hook_args,
    )
    if hook_payload and int(hook_payload.get("matched_hooks") or 0) > 0:
        if hook_payload.get("decision") == "block":
            if not _claim_entry_continuation(payload, state_dir, hook_payload):
                return _allow()
            reason = str(
                hook_payload.get("reason")
                or "Continue the active statem-managed run."
            )
            run_id = str(hook_payload.get("run_id") or "")
            entry_id = str(hook_payload.get("current_entry_id") or "")
            if _current_entry_has_goto_blocked(state_dir, run_id, entry_id):
                reason += (
                    "\n\nBlocked transition repair continuation:\n"
                    "The current entry recorded a blocked transition. Preserve "
                    "already passing evidence, repair the exact failed gate, and "
                    "rerun that transition before stopping. Do not create a new "
                    "candidate or weaken the gate."
                )
            return _continue(reason)
        return _allow()

    if _require_state_hooks():
        return _allow()

    if payload.get("stop_hook_active") is True:
        return _allow()

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


def _require_state_hooks() -> bool:
    return os.environ.get("STATEM_STOP_REQUIRE_STATE_HOOKS", "").strip().lower() in {"1", "true", "yes", "on"}


def _claim_entry_continuation(
    payload: dict[str, Any],
    state_dir: Path,
    hook_payload: dict[str, Any],
) -> bool:
    """Claim one bounded Stop continuation for the current StateM entry."""

    run_id = str(hook_payload.get("run_id") or "")
    entry_id = str(hook_payload.get("current_entry_id") or "")
    if not run_id or not entry_id:
        return payload.get("stop_hook_active") is not True

    session_id = str(payload.get("session_id") or "default")
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    marker_dir = state_dir / "host-hooks"
    marker_path = marker_dir / f"stop-{session_key}.json"
    marker = _read_json_file(marker_path)
    same_entry = (
        marker.get("run_id") == run_id
        and marker.get("current_entry_id") == entry_id
    )
    continuation_count = int(marker.get("continuation_count") or 0) if same_entry else 0
    if (
        payload.get("stop_hook_active") is True
        and same_entry
        and continuation_count
        >= _entry_continuation_budget(state_dir, run_id, entry_id)
    ):
        return False

    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        temp_path = marker_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "current_entry_id": entry_id,
                    "continuation_count": continuation_count + 1,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, marker_path)
    except OSError:
        return payload.get("stop_hook_active") is not True
    return True


def _entry_continuation_budget(
    state_dir: Path,
    run_id: str,
    entry_id: str,
) -> int:
    raw = os.environ.get("STATEM_STOP_MAX_CONTINUATIONS_PER_ENTRY", "").strip()
    if not raw:
        base = DEFAULT_ENTRY_CONTINUATION_BUDGET
    else:
        try:
            base = int(raw)
        except ValueError:
            base = DEFAULT_ENTRY_CONTINUATION_BUDGET
    base = min(10, max(1, base))
    extra = _blocked_transition_extra_budget()
    if extra and _current_entry_has_goto_blocked(state_dir, run_id, entry_id):
        return min(10, base + extra)
    return base


def _blocked_transition_extra_budget() -> int:
    raw = os.environ.get(
        "STATEM_STOP_EXTRA_CONTINUATIONS_AFTER_GOTO_BLOCKED",
        "",
    ).strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return min(3, max(0, value))


def _current_entry_has_goto_blocked(
    state_dir: Path,
    run_id: str,
    entry_id: str,
) -> bool:
    if not run_id or not entry_id:
        return False
    state = _read_json_file(state_dir / "runs" / run_id / "state.json")
    history = state.get("history")
    if not isinstance(history, list):
        return False
    return any(
        isinstance(event, dict)
        and event.get("event") == "goto_blocked"
        and event.get("current_entry_id") == entry_id
        for event in history
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_statem_json(statem_cmd: str, cwd: Path, state_dir: Path, *args: str) -> dict[str, Any] | None:
    try:
        argv = [*shlex.split(statem_cmd), *args, "--state-dir", str(state_dir), "--json"]
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
