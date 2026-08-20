#!/usr/bin/env python3
"""Durable lifecycle supervision for detached TeamRun worker launchers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .teamrun_worker_loop import main as worker_loop_main
except ImportError:
    from teamrun_worker_loop import main as worker_loop_main  # type: ignore[no-redef]


TERMINAL_STATES = {"completed", "failed", "canceled", "orphaned"}
_LOCAL_CHILDREN: dict[int, subprocess.Popen[Any]] = {}


def spawn_lifecycle(
    *,
    loop_args: list[str],
    handle_file: Path,
    run_id: str,
    entry_id: str,
    wall_timeout: float | None,
) -> dict[str, Any]:
    handle_file = handle_file.expanduser().resolve()
    if handle_file.exists():
        existing = lifecycle_status(handle_file)
        if existing.get("state") not in TERMINAL_STATES:
            raise ValueError(f"TeamRun lifecycle handle is already active: {handle_file}")

    handle_file.parent.mkdir(parents=True, exist_ok=True)
    launched_at = time.time()
    handle_id = hashlib.sha256(
        f"{run_id}\0{entry_id}\0{launched_at}\0{os.getpid()}".encode("utf-8")
    ).hexdigest()[:24]
    spec_file = handle_file.with_suffix(handle_file.suffix + ".spec.json")
    stdout_file = handle_file.with_suffix(handle_file.suffix + ".stdout.txt")
    stderr_file = handle_file.with_suffix(handle_file.suffix + ".stderr.txt")
    _write_json(spec_file, {"version": 1, "loop_args": loop_args})
    receipt: dict[str, Any] = {
        "version": 1,
        "kind": "teamrun_worker_lifecycle",
        "handle_id": handle_id,
        "run_id": run_id,
        "entry_id": entry_id,
        "state": "launching",
        "pid": None,
        "process_group_id": None,
        "launched_at_epoch": launched_at,
        "deadline_at_epoch": (
            launched_at + float(wall_timeout) if wall_timeout is not None else None
        ),
        "spec_file": str(spec_file),
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
        "returncode": None,
        "finished_at_epoch": None,
    }
    _write_json(handle_file, receipt)

    script = Path(__file__).resolve()
    with stdout_file.open("w", encoding="utf-8") as stdout, stderr_file.open(
        "w", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            [sys.executable, str(script), "child", "--handle-file", str(handle_file)],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            close_fds=True,
        )
    receipt["state"] = "running"
    receipt["pid"] = process.pid
    receipt["process_group_id"] = process.pid
    _LOCAL_CHILDREN[process.pid] = process
    _write_json(handle_file, receipt)
    return receipt


def lifecycle_status(
    handle_file: Path,
    *,
    run_id: str | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    handle_file = handle_file.expanduser().resolve()
    receipt = _read_json(handle_file)
    _require_handle(receipt)
    pid = int(receipt.get("pid") or 0)
    local_process = _LOCAL_CHILDREN.get(pid)
    if local_process is not None and local_process.poll() is not None:
        _LOCAL_CHILDREN.pop(pid, None)
        receipt = _read_json(handle_file)
    if receipt.get("state") in {"launching", "running"}:
        if pid and not _pid_alive(pid):
            receipt["state"] = "orphaned"
            receipt["finished_at_epoch"] = time.time()
            receipt["error"] = "lifecycle supervisor exited without recording a terminal state"
            _write_json(handle_file, receipt)
    if run_id is not None:
        _require_scope(receipt, run_id=run_id, entry_id=entry_id)
    return receipt


def require_completed_lifecycle(
    handle_file: Path, *, run_id: str, entry_id: str
) -> dict[str, Any]:
    receipt = lifecycle_status(handle_file, run_id=run_id, entry_id=entry_id)
    if receipt.get("state") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(
            "TeamRun lifecycle is not successfully completed: "
            f"state={receipt.get('state')!r} returncode={receipt.get('returncode')!r}"
        )
    return receipt


def join_lifecycle(
    handle_file: Path,
    *,
    run_id: str,
    entry_id: str,
    timeout: float | None,
    poll_seconds: float = 0.25,
) -> dict[str, Any]:
    deadline = time.monotonic() + float(timeout) if timeout is not None else None
    while True:
        receipt = lifecycle_status(handle_file)
        _require_scope(receipt, run_id=run_id, entry_id=entry_id)
        if receipt["state"] in TERMINAL_STATES:
            return receipt
        receipt_deadline = receipt.get("deadline_at_epoch")
        deadline_expired = (
            isinstance(receipt_deadline, (int, float)) and time.time() >= receipt_deadline
        )
        join_expired = deadline is not None and time.monotonic() >= deadline
        if deadline_expired or join_expired:
            canceled = cancel_lifecycle(
                handle_file,
                run_id=run_id,
                entry_id=entry_id,
                reason="join deadline expired",
            )
            canceled["join_timed_out"] = True
            _write_json(handle_file.expanduser().resolve(), canceled)
            return canceled
        time.sleep(max(0.05, poll_seconds))


def cancel_lifecycle(
    handle_file: Path,
    *,
    run_id: str,
    entry_id: str | None,
    reason: str,
    grace_seconds: float = 1.0,
) -> dict[str, Any]:
    handle_file = handle_file.expanduser().resolve()
    receipt = lifecycle_status(handle_file)
    _require_scope(receipt, run_id=run_id, entry_id=entry_id)
    if receipt["state"] in TERMINAL_STATES:
        return receipt
    pid = int(receipt.get("process_group_id") or receipt.get("pid") or 0)
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        until = time.monotonic() + max(0.0, grace_seconds)
        while _pid_alive(pid) and time.monotonic() < until:
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    receipt["state"] = "canceled"
    receipt["returncode"] = 143
    receipt["finished_at_epoch"] = time.time()
    receipt["cancel_reason"] = reason
    _write_json(handle_file, receipt)
    return receipt


def _run_child(handle_file: Path) -> int:
    handle_file = handle_file.expanduser().resolve()
    receipt = _wait_for_parent_receipt(handle_file)
    spec = _read_json(Path(str(receipt["spec_file"])))
    loop_args = spec.get("loop_args")
    if not isinstance(loop_args, list) or not all(isinstance(item, str) for item in loop_args):
        raise ValueError("invalid TeamRun lifecycle child specification")
    try:
        returncode = int(worker_loop_main(loop_args))
        state = "completed" if returncode == 0 else "failed"
        error = None
    except BaseException as exc:
        returncode = 1
        state = "failed"
        error = f"{type(exc).__name__}: {exc}"
    latest = _read_json(handle_file)
    if latest.get("state") == "canceled":
        return 143
    latest["state"] = state
    latest["returncode"] = returncode
    latest["finished_at_epoch"] = time.time()
    if error:
        latest["error"] = error
    _write_json(handle_file, latest)
    return returncode


def _wait_for_parent_receipt(handle_file: Path) -> dict[str, Any]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        receipt = _read_json(handle_file)
        if receipt.get("state") == "running" and receipt.get("pid") == os.getpid():
            return receipt
        time.sleep(0.02)
    raise ValueError("parent did not publish the running lifecycle receipt")


def _require_scope(
    receipt: dict[str, Any], *, run_id: str, entry_id: str | None
) -> None:
    if receipt.get("run_id") != run_id:
        raise ValueError("TeamRun lifecycle handle belongs to another run")
    if entry_id is not None and receipt.get("entry_id") != entry_id:
        raise ValueError("TeamRun lifecycle handle belongs to another entry")


def _require_handle(receipt: dict[str, Any]) -> None:
    if receipt.get("version") != 1 or receipt.get("kind") != "teamrun_worker_lifecycle":
        raise ValueError("invalid TeamRun lifecycle handle")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    child = subparsers.add_parser("child")
    child.add_argument("--handle-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "child":
        return _run_child(args.handle_file)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
