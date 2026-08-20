from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any


DEFAULT_DEADLINE = Path("/tmp/statem-verification-checks/deadline.json")
DEFAULT_HEAVY_WORK_BUFFER_SECONDS = 240
DEFAULT_HANDOFF_BUFFER_SECONDS = 120
DEFAULT_MIN_EXPENSIVE_TIMEOUT_SECONDS = 30
DEFAULT_MIN_ARTIFACT_RESCUE_TIMEOUT_SECONDS = 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print statem benchmark deadline status.")
    parser.add_argument("--deadline", default=str(DEFAULT_DEADLINE), help="Path to deadline.json.")
    parser.add_argument(
        "--require-mode",
        action="append",
        default=[],
        help="Require one of these deadline modes. May be repeated or comma-separated. Unconfigured deadlines pass.",
    )
    parser.add_argument(
        "--min-remaining",
        type=int,
        help="Require at least this many remaining seconds. Unconfigured deadlines pass.",
    )
    parser.add_argument(
        "--handoff-due-or-expired",
        action="store_true",
        help="Pass only when a configured deadline is in handoff_due or expired mode.",
    )
    parser.add_argument(
        "--heavy-work-closed-or-worse",
        action="store_true",
        help="Pass only when a configured deadline is heavy_work_closed, handoff_due, or expired.",
    )
    parser.add_argument(
        "--suggest-timeout",
        choices=("bootstrap", "normal", "expensive", "artifact_rescue"),
        help="Print a bounded timeout suggestion for a new command of this cost class.",
    )
    parser.add_argument(
        "--seconds-only",
        action="store_true",
        help="With --suggest-timeout, print only the integer timeout seconds for shell use.",
    )
    args = parser.parse_args(argv)

    status = get_deadline_status(Path(args.deadline))
    predicate_problems = deadline_predicate_problems(
        status,
        required_modes=_split_modes(args.require_mode),
        min_remaining=args.min_remaining,
        handoff_due_or_expired=args.handoff_due_or_expired,
        heavy_work_closed_or_worse=args.heavy_work_closed_or_worse,
    )
    if args.suggest_timeout:
        if args.suggest_timeout == "artifact_rescue":
            seconds = suggest_artifact_rescue_timeout_seconds(status)
            label = "suggested_artifact_rescue_timeout_seconds"
        elif args.suggest_timeout == "bootstrap":
            seconds = suggest_expensive_timeout_seconds(status)
            label = "suggested_bootstrap_timeout_seconds"
        elif args.suggest_timeout == "normal":
            seconds = suggest_expensive_timeout_seconds(status)
            label = "suggested_normal_timeout_seconds"
        else:
            seconds = suggest_expensive_timeout_seconds(status)
            label = "suggested_expensive_timeout_seconds"
        if args.seconds_only:
            print(0 if seconds is None else seconds)
        else:
            print(format_deadline_status(status))
            if seconds is None:
                print(f"{label}=unbounded")
            else:
                print(f"{label}={seconds}")
        if predicate_problems:
            for problem in predicate_problems:
                print(problem)
        return 1 if predicate_problems else 0

    print(format_deadline_status(status))
    for problem in predicate_problems:
        print(problem)
    return 1 if predicate_problems else 0


def get_deadline_status(
    path: Path = DEFAULT_DEADLINE,
    *,
    now: float | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = payload if payload is not None else _read_json(path)
    if not isinstance(data, dict) or not data:
        return {
            "configured": False,
            "mode": "unbounded",
            "remaining_seconds": None,
            "path": str(path),
        }

    now = time.time() if now is None else now
    deadline_at = _float_value(data.get("deadline_at_epoch"))
    started_at = _float_value(data.get("started_at_epoch"))
    handoff_buffer = _positive_int(data.get("handoff_buffer_seconds"), DEFAULT_HANDOFF_BUFFER_SECONDS)
    heavy_buffer = _positive_int(data.get("heavy_work_buffer_seconds"), DEFAULT_HEAVY_WORK_BUFFER_SECONDS)
    if deadline_at is None:
        return {
            "configured": False,
            "mode": "unbounded",
            "remaining_seconds": None,
            "path": str(path),
            "error": "missing deadline_at_epoch",
        }

    remaining = int(math.floor(deadline_at - now))
    if remaining <= 0:
        mode = "expired"
    elif remaining <= handoff_buffer:
        mode = "handoff_due"
    elif remaining <= heavy_buffer:
        mode = "heavy_work_closed"
    else:
        mode = "normal"

    status: dict[str, Any] = {
        "configured": True,
        "mode": mode,
        "remaining_seconds": remaining,
        "handoff_buffer_seconds": handoff_buffer,
        "heavy_work_buffer_seconds": heavy_buffer,
        "deadline_at_epoch": deadline_at,
        "path": str(path),
    }
    if started_at is not None:
        status["elapsed_seconds"] = max(0, int(math.floor(now - started_at)))
    for key in ("run_id", "source", "agent_deadline_seconds"):
        if key in data:
            status[key] = data[key]
    return status


def format_deadline_status(status: dict[str, Any]) -> str:
    if not status.get("configured"):
        return "deadline_status mode=unbounded configured=false"
    parts = [
        f"deadline_status mode={status.get('mode')}",
        f"remaining_seconds={status.get('remaining_seconds')}",
        f"handoff_buffer_seconds={status.get('handoff_buffer_seconds')}",
        f"heavy_work_buffer_seconds={status.get('heavy_work_buffer_seconds')}",
    ]
    elapsed = status.get("elapsed_seconds")
    if elapsed is not None:
        parts.append(f"elapsed_seconds={elapsed}")
    run_id = status.get("run_id")
    if run_id:
        parts.append(f"run_id={run_id}")
    return " ".join(parts)


def deadline_handoff_due(status: dict[str, Any]) -> bool:
    return bool(status.get("configured")) and status.get("mode") in {"handoff_due", "expired"}


def deadline_heavy_work_closed(status: dict[str, Any]) -> bool:
    return bool(status.get("configured")) and status.get("mode") in {
        "heavy_work_closed",
        "handoff_due",
        "expired",
    }


def deadline_predicate_problems(
    status: dict[str, Any],
    *,
    required_modes: set[str] | None = None,
    min_remaining: int | None = None,
    handoff_due_or_expired: bool = False,
    heavy_work_closed_or_worse: bool = False,
) -> list[str]:
    problems: list[str] = []
    configured = bool(status.get("configured"))
    mode = str(status.get("mode") or "unbounded")

    if required_modes and configured and mode not in required_modes:
        problems.append(
            "deadline_status predicate failed: "
            f"mode {mode!r} not in required modes {', '.join(sorted(required_modes))}"
        )
    if min_remaining is not None:
        if min_remaining < 0:
            problems.append("deadline_status predicate failed: --min-remaining must be nonnegative")
        elif configured:
            remaining = _positive_or_zero_int(status.get("remaining_seconds"))
            if remaining is None or remaining < min_remaining:
                problems.append(
                    "deadline_status predicate failed: "
                    f"remaining_seconds={remaining} < min_remaining={min_remaining}"
                )
    if handoff_due_or_expired and not deadline_handoff_due(status):
        problems.append(
            "deadline_status predicate failed: deadline is not handoff_due or expired "
            f"(mode={mode})"
        )
    if heavy_work_closed_or_worse and not deadline_heavy_work_closed(status):
        problems.append(
            "deadline_status predicate failed: deadline has not closed heavy work "
            f"(mode={mode})"
        )
    return problems


def suggest_expensive_timeout_seconds(
    status: dict[str, Any],
    *,
    min_seconds: int = DEFAULT_MIN_EXPENSIVE_TIMEOUT_SECONDS,
) -> int | None:
    """Return a safe outer timeout for starting one new expensive command.

    The suggestion preserves both the heavy-work and handoff buffers so the
    agent still has time to write receipts, verify, self-review, and hand off.
    A return value of 0 means no new expensive command should be started.
    None means no deadline is configured.
    """
    if not status.get("configured"):
        return None
    remaining = _positive_or_zero_int(status.get("remaining_seconds"))
    if remaining is None:
        return None
    reserve = (
        _positive_int(status.get("heavy_work_buffer_seconds"), DEFAULT_HEAVY_WORK_BUFFER_SECONDS)
        + _positive_int(status.get("handoff_buffer_seconds"), DEFAULT_HANDOFF_BUFFER_SECONDS)
    )
    budget = remaining - reserve
    if budget < min_seconds:
        return 0
    return budget


def suggest_artifact_rescue_timeout_seconds(
    status: dict[str, Any],
    *,
    min_seconds: int = DEFAULT_MIN_ARTIFACT_RESCUE_TIMEOUT_SECONDS,
) -> int | None:
    """Return a bounded timeout for one last required-artifact rescue.

    This is intentionally narrower than a normal expensive-command budget: it
    preserves handoff time, but not the full heavy-work buffer. Agents should
    use it only when the required final artifact is missing or unusable, not for
    broad quality tuning after a runnable candidate already exists.
    """
    if not status.get("configured"):
        return None
    remaining = _positive_or_zero_int(status.get("remaining_seconds"))
    if remaining is None:
        return None
    reserve = _positive_int(status.get("handoff_buffer_seconds"), DEFAULT_HANDOFF_BUFFER_SECONDS)
    budget = remaining - reserve
    if budget < min_seconds:
        return 0
    return budget


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _float_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _positive_or_zero_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else 0


def _split_modes(raw_items: list[str]) -> set[str]:
    modes: set[str] = set()
    for raw_item in raw_items:
        for part in str(raw_item).split(","):
            mode = part.strip()
            if mode:
                modes.add(mode)
    return modes


if __name__ == "__main__":
    raise SystemExit(main())
