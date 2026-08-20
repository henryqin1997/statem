#!/usr/bin/env python3
"""Launch parallel Codex subagents for statem TeamRun tasks."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path

try:
    from .teamrun_lifecycle import (
        cancel_lifecycle,
        join_lifecycle,
        lifecycle_status,
        require_completed_lifecycle,
        spawn_lifecycle,
    )
    from .teamrun_worker_loop import main as worker_loop_main
except ImportError:
    from teamrun_lifecycle import (  # type: ignore[no-redef]
        cancel_lifecycle,
        join_lifecycle,
        lifecycle_status,
        require_completed_lifecycle,
        spawn_lifecycle,
    )
    from teamrun_worker_loop import main as worker_loop_main  # type: ignore[no-redef]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    lifecycle_action = _lifecycle_action(args)
    if lifecycle_action != "run":
        return _run_lifecycle_action(args, lifecycle_action)
    lease_seconds = int(args.lease_seconds)
    if lease_seconds <= 0:
        lease_seconds = int(args.timeout) + 60 if args.timeout else 600
    wall_timeout = args.wall_timeout
    if wall_timeout is None and args.timeout is not None:
        wall_timeout = float(args.timeout) * max(1, int(args.max_rounds)) + max(60.0, float(args.return_slack) * 2.0)
    wall_timeout = _bounded_wall_timeout(
        wall_timeout,
        deadline_file=Path(args.deadline_file) if args.deadline_file else None,
        reserve_seconds=float(args.deadline_reserve_seconds),
    )
    script_dir = Path(__file__).resolve().parent
    worker_script = script_dir / "teamrun_codex_worker.py"
    worker_argv = [
        sys.executable,
        str(worker_script),
        "--codex-command",
        args.codex_command,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--agent-role",
        args.agent_role,
        "--execution-profile",
        args.execution_profile,
    ]
    if args.no_bypass:
        worker_argv.append("--no-bypass")
    if args.no_unified_exec:
        worker_argv.append("--no-unified-exec")
    for extra in args.extra_codex_arg:
        worker_argv.extend(["--extra-codex-arg", extra])

    loop_args = [
        "--run-id",
        args.run_id,
        "--worker-command",
        shlex.join(worker_argv),
        "--max-workers",
        str(args.max_workers),
        "--max-rounds",
        str(args.max_rounds),
        "--lease-seconds",
        str(lease_seconds),
        "--agent-prefix",
        args.agent_prefix,
        "--agent-role",
        args.agent_role,
    ]
    if args.entry_id:
        loop_args.extend(["--entry-id", args.entry_id])
    if args.state_dir:
        loop_args.extend(["--state-dir", args.state_dir])
    if args.cwd:
        loop_args.extend(["--cwd", args.cwd])
    if args.statem_command:
        loop_args.extend(["--statem-command", args.statem_command])
    if args.runner_dir:
        loop_args.extend(["--runner-dir", args.runner_dir])
    if args.timeout is not None:
        loop_args.extend(["--timeout", str(args.timeout)])
    loop_args.extend(["--return-slack", str(args.return_slack)])
    if wall_timeout is not None:
        loop_args.extend(["--wall-timeout", str(wall_timeout)])
    if args.once:
        loop_args.append("--once")
    if args.poll_seconds:
        loop_args.extend(["--poll-seconds", str(args.poll_seconds)])
    if args.json:
        loop_args.append("--json")
    if args.detach:
        if not args.entry_id:
            raise SystemExit("--detach requires --entry-id")
        if not args.handle_file:
            raise SystemExit("--detach requires --handle-file")
        receipt = spawn_lifecycle(
            loop_args=loop_args,
            handle_file=Path(args.handle_file),
            run_id=args.run_id,
            entry_id=args.entry_id,
            wall_timeout=wall_timeout,
        )
        _emit(receipt, as_json=args.json)
        return 0
    return worker_loop_main(loop_args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex subagents against statem TeamRun tasks.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--entry-id", default=os.environ.get("STATEM_ENTRY_ID"))
    parser.add_argument("--state-dir", default=os.environ.get("STATEM_STATE_DIR"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--statem-command", default=os.environ.get("STATEM_COMMAND"))
    parser.add_argument("--runner-dir")
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=0,
        help="lease duration; defaults to worker timeout + 60s, or 600s without a timeout",
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--wall-timeout", type=float, default=None, help="overall launcher budget in seconds")
    parser.add_argument("--return-slack", type=float, default=30.0, help="seconds workers should reserve to summarize before timeout")
    parser.add_argument("--deadline-file", default="/tmp/statem-verification-checks/deadline.json")
    parser.add_argument("--deadline-reserve-seconds", type=float, default=120.0)
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--handle-file")
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument("--status-handle", action="store_true")
    lifecycle.add_argument("--join-handle", action="store_true")
    lifecycle.add_argument("--cancel-handle", action="store_true")
    lifecycle.add_argument("--require-completed-handle", action="store_true")
    parser.add_argument("--join-timeout", type=float)
    parser.add_argument("--cancel-reason", default="requested by lifecycle owner")
    parser.add_argument("--agent-prefix", default="codex-worker")
    parser.add_argument("--agent-role", default="team-worker")
    parser.add_argument("--codex-command", default=os.environ.get("STATEM_CODEX_COMMAND", "codex"))
    parser.add_argument("--model", default=os.environ.get("STATEM_CODEX_MODEL", "gpt-5.5"))
    parser.add_argument("--reasoning-effort", default=os.environ.get("STATEM_CODEX_REASONING_EFFORT", "high"))
    parser.add_argument(
        "--execution-profile",
        choices=("default", "read-only-review"),
        default="default",
    )
    parser.add_argument("--extra-codex-arg", action="append", default=[])
    parser.add_argument("--no-bypass", action="store_true")
    parser.add_argument("--no-unified-exec", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _lifecycle_action(args: argparse.Namespace) -> str:
    if args.status_handle:
        return "status"
    if args.join_handle:
        return "join"
    if args.cancel_handle:
        return "cancel"
    if args.require_completed_handle:
        return "require-completed"
    return "run"


def _run_lifecycle_action(args: argparse.Namespace, action: str) -> int:
    if not args.handle_file:
        raise SystemExit(f"--{action}-handle requires --handle-file")
    handle_file = Path(args.handle_file)
    if action == "status":
        receipt = lifecycle_status(
            handle_file,
            run_id=args.run_id,
            entry_id=args.entry_id or None,
        )
    elif action == "require-completed":
        if not args.entry_id:
            raise SystemExit("--require-completed-handle requires --entry-id")
        receipt = require_completed_lifecycle(
            handle_file,
            run_id=args.run_id,
            entry_id=args.entry_id,
        )
    elif action == "join":
        if not args.entry_id:
            raise SystemExit("--join-handle requires --entry-id")
        receipt = join_lifecycle(
            handle_file,
            run_id=args.run_id,
            entry_id=args.entry_id,
            timeout=args.join_timeout,
        )
    else:
        receipt = cancel_lifecycle(
            handle_file,
            run_id=args.run_id,
            entry_id=args.entry_id or None,
            reason=args.cancel_reason,
        )
    _emit(receipt, as_json=args.json)
    if action in {"status", "require-completed"}:
        return 0
    return 0 if receipt.get("state") == "completed" else 1


def _bounded_wall_timeout(
    wall_timeout: float | None,
    *,
    deadline_file: Path | None,
    reserve_seconds: float,
) -> float | None:
    if deadline_file is None or not deadline_file.is_file():
        return wall_timeout
    payload = json.loads(deadline_file.read_text(encoding="utf-8"))
    deadline_at = payload.get("deadline_at_epoch") if isinstance(payload, dict) else None
    if not isinstance(deadline_at, (int, float)):
        return wall_timeout
    available = float(deadline_at) - time.time() - max(0.0, reserve_seconds)
    if available <= 0:
        raise SystemExit("TeamRun lifecycle deadline leaves no worker budget after reserve")
    return available if wall_timeout is None else min(float(wall_timeout), available)


def _emit(receipt: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(
            f"TeamRun lifecycle {receipt.get('handle_id')} state={receipt.get('state')} "
            f"run={receipt.get('run_id')} entry={receipt.get('entry_id')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
