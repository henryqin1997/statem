#!/usr/bin/env python3
"""Host-side TeamRun worker launcher.

This script does not mutate statem runtime files directly. It claims TeamRun
tasks through the CLI, runs a worker command with a scoped prompt and
environment variables, then submits the worker's JSON result through the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ClaimedTask:
    task_id: str
    agent_id: str
    assignment_path: str
    prompt: str
    prompt_path: Path
    result_path: Path
    report_path: Path
    work_dir: Path
    stdout_path: Path
    stderr_path: Path
    returncode_path: Path


@dataclass
class WorkerResult:
    task: ClaimedTask
    returncode: int
    submitted: bool
    result_path: str
    error: str = ""


@dataclass
class RunningWorker:
    task: ClaimedTask
    process: subprocess.Popen[str] | None
    hard_deadline: float | None
    return_deadline_epoch: float | None
    startup_error: str = ""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cwd = Path(args.cwd).expanduser().resolve()
    state_dir = Path(args.state_dir or os.environ.get("STATEM_STATE_DIR") or cwd / ".statem").expanduser()
    if not state_dir.is_absolute():
        state_dir = (cwd / state_dir).resolve()
    statem_cmd = args.statem_command or f"{sys.executable} -m statem.cli"

    entry_id = args.entry_id or _current_entry_id(statem_cmd, cwd, state_dir, args.run_id)
    if not entry_id:
        _emit_error("Could not determine current entry id; pass --entry-id")
        return 1
    args.entry_id = entry_id
    args.state_dir = str(state_dir)

    summary: dict[str, Any] = {
        "ok": True,
        "run_id": args.run_id,
        "entry_id": entry_id,
        "rounds": [],
        "claimed": 0,
        "submitted": 0,
        "reported": 0,
        "report_errors": 0,
        "failed": 0,
        "timed_out": False,
    }
    wall_deadline = time.monotonic() + float(args.wall_timeout) if args.wall_timeout is not None else None

    for round_index in range(1, int(args.max_rounds) + 1):
        if _wall_time_exhausted(wall_deadline):
            summary["ok"] = False
            summary["timed_out"] = True
            summary["rounds"].append({"round": round_index, "claimed": [], "reason": "wall_timeout"})
            break
        try:
            status = _statem_json(statem_cmd, cwd, state_dir, args.run_id, ["team", "status", "--entry-id", entry_id])
        except RuntimeError as exc:
            summary["ok"] = False
            summary["rounds"].append({"round": round_index, "error": str(exc)})
            break
        counts = status.get("counts") or {}
        if int(counts.get("open") or 0) <= 0:
            summary["rounds"].append({"round": round_index, "claimed": [], "reason": "no_open_tasks"})
            break

        claims = _claim_round(statem_cmd, cwd, state_dir, args, round_index)
        if not claims:
            summary["rounds"].append({"round": round_index, "claimed": [], "reason": "claim_unavailable"})
            break
        summary["claimed"] += len(claims)

        results = _run_workers(args, claims, cwd, wall_deadline)
        report_summary = _submit_reports(
            statem_cmd,
            cwd,
            state_dir,
            args.run_id,
            entry_id,
            results,
            args.agent_role,
        )
        submitted = _submit_results(
            statem_cmd,
            cwd,
            state_dir,
            args.run_id,
            entry_id,
            results,
            args.agent_role,
        )
        summary["reported"] += int(report_summary["reported"])
        summary["report_errors"] += int(report_summary["errors"])
        summary["submitted"] += sum(1 for result in submitted if result.submitted)
        summary["failed"] += sum(1 for result in submitted if result.error)
        summary["rounds"].append(
            {
                "round": round_index,
                "claimed": [task.task_id for task in claims],
                "results": [
                    {
                        "task_id": result.task.task_id,
                        "agent_id": result.task.agent_id,
                        "returncode": result.returncode,
                        "submitted": result.submitted,
                        "result_path": result.result_path,
                        "error": result.error,
                    }
                    for result in submitted
                ],
                "reported": report_summary["reported"],
                "report_errors": report_summary["errors"],
            }
        )
        if _wall_time_exhausted(wall_deadline):
            summary["ok"] = False
            summary["timed_out"] = True
            break
        if args.once:
            break
        if args.poll_seconds > 0:
            time.sleep(float(args.poll_seconds))

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_summary(summary)
    return 0 if summary["ok"] and summary["failed"] == 0 else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local workers against statem TeamRun tasks.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--entry-id", default=os.environ.get("STATEM_ENTRY_ID"))
    parser.add_argument("--state-dir", default=os.environ.get("STATEM_STATE_DIR"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--statem-command", default=os.environ.get("STATEM_COMMAND"))
    parser.add_argument("--worker-command", required=True, help="command that writes result JSON")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=1)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--wall-timeout", type=float, default=None, help="overall launcher budget in seconds")
    parser.add_argument("--return-slack", type=float, default=30.0, help="seconds reserved for a worker to summarize before hard timeout")
    parser.add_argument("--agent-prefix", default="team-worker")
    parser.add_argument(
        "--agent-role",
        default=os.environ.get("STATEM_TEAM_AGENT_ROLE", "team-worker"),
        help="StateM producer role recorded for every claimed worker result",
    )
    parser.add_argument("--runner-dir", help="directory for prompts, logs, and worker result files")
    parser.add_argument("--json", action="store_true")
    return parser


def _current_entry_id(statem_cmd: str, cwd: Path, state_dir: Path, run_id: str) -> str:
    try:
        cur = _statem_json(statem_cmd, cwd, state_dir, run_id, ["cur"])
    except RuntimeError:
        return ""
    return str(cur.get("current_entry_id") or "")


def _claim_round(
    statem_cmd: str,
    cwd: Path,
    state_dir: Path,
    args: argparse.Namespace,
    round_index: int,
) -> list[ClaimedTask]:
    claims: list[ClaimedTask] = []
    max_workers = max(1, int(args.max_workers))
    for slot in range(max_workers):
        agent_id = f"{args.agent_prefix}-{round_index}-{slot + 1}"
        try:
            claimed = _statem_json(
                statem_cmd,
                cwd,
                state_dir,
                args.run_id,
                [
                    "team",
                    "claim",
                    "--entry-id",
                    args.entry_id,
                    "--agent-id",
                    agent_id,
                    "--agent-role",
                    args.agent_role,
                    "--lease-seconds",
                    str(args.lease_seconds),
                    "--worker-index",
                    str(slot),
                    "--worker-count",
                    str(max_workers),
                ],
            )
        except RuntimeError as exc:
            if claims:
                break
            if "No open TeamRun tasks" in str(exc) or "max_parallel" in str(exc):
                break
            raise
        task = claimed["claimed_task"]
        task_id = str(task["task_id"])
        prompt_payload = _statem_json(
            statem_cmd,
            cwd,
            state_dir,
            args.run_id,
            ["team", "prompt", task_id, "--entry-id", args.entry_id],
        )
        base_dir = Path(args.runner_dir).expanduser().resolve() if args.runner_dir else Path(str(claimed.get("path") or cwd / ".statem")) / "runner"
        runner_dir = base_dir / f"round-{round_index}" / agent_id / task_id
        runner_dir.mkdir(parents=True, exist_ok=True)
        worker_work_dir = Path(str(task.get("work_dir") or runner_dir / "work")).expanduser().resolve()
        worker_work_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = runner_dir / "prompt.md"
        result_path = runner_dir / "result.json"
        report_path = worker_work_dir / "report.json"
        stdout_path = runner_dir / "stdout.txt"
        stderr_path = runner_dir / "stderr.txt"
        returncode_path = runner_dir / "returncode.txt"
        prompt = str(prompt_payload["prompt"])
        prompt_path.write_text(prompt, encoding="utf-8")
        claims.append(
            ClaimedTask(
                task_id=task_id,
                agent_id=agent_id,
                assignment_path=str(task["assignment_path"]),
                prompt=prompt,
                prompt_path=prompt_path,
                result_path=result_path,
                report_path=report_path,
                work_dir=worker_work_dir,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                returncode_path=returncode_path,
            )
        )
    return claims


def _run_workers(
    args: argparse.Namespace,
    claims: list[ClaimedTask],
    cwd: Path,
    wall_deadline: float | None,
) -> list[WorkerResult]:
    workers: list[RunningWorker] = []
    for task in claims:
        if _wall_time_exhausted(wall_deadline):
            _write_failure_result(task, 124, "launcher wall timeout before worker start", "", "")
            workers.append(RunningWorker(task, None, None, None, "launcher wall timeout before worker start"))
            continue
        launch_timeout = _remaining_timeout(args.timeout, wall_deadline)
        if launch_timeout is not None and launch_timeout <= 0:
            _write_failure_result(task, 124, "launcher wall timeout before worker start", "", "")
            workers.append(RunningWorker(task, None, None, None, "launcher wall timeout before worker start"))
            continue
        hard_deadline = None if launch_timeout is None else time.monotonic() + float(launch_timeout)
        return_deadline_epoch = _return_deadline_epoch(launch_timeout, float(args.return_slack))
        env = {
            **os.environ,
            "STATEM_RUN_ID": args.run_id,
            "STATEM_ENTRY_ID": args.entry_id or "",
            "STATEM_STATE_DIR": str(Path(args.state_dir).expanduser().resolve()) if args.state_dir else "",
            "STATEM_TEAM_TASK_ID": task.task_id,
            "STATEM_TEAM_AGENT_ID": task.agent_id,
            "STATEM_TEAM_AGENT_ROLE": args.agent_role,
            "STATEM_TEAM_ASSIGNMENT_FILE": task.assignment_path,
            "STATEM_TEAM_PROMPT_FILE": str(task.prompt_path),
            "STATEM_TEAM_RESULT_FILE": str(task.result_path),
            "STATEM_TEAM_REPORT_FILE": str(task.report_path),
            "STATEM_TEAM_WORK_DIR": str(task.work_dir),
            "STATEM_TEAM_RETURN_SLACK_SECONDS": f"{float(args.return_slack):.3f}",
        }
        if launch_timeout is not None:
            env["STATEM_TEAM_WORKER_TIMEOUT_SECONDS"] = f"{float(launch_timeout):.3f}"
        if return_deadline_epoch is not None:
            env["STATEM_TEAM_RETURN_DEADLINE_EPOCH"] = f"{return_deadline_epoch:.3f}"
            env["STATEM_TEAM_RETURN_DEADLINE"] = _format_epoch_utc(return_deadline_epoch)
        process = subprocess.Popen(
            _format_worker_command(args.worker_command, task),
            cwd=cwd,
            shell=True,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        workers.append(RunningWorker(task, process, hard_deadline, return_deadline_epoch))

    results: list[WorkerResult] = []
    for worker in workers:
        task = worker.task
        process = worker.process
        if process is None:
            results.append(WorkerResult(task, 124, False, str(task.result_path), worker.startup_error))
            continue
        timeout = _remaining_process_timeout(worker.hard_deadline, wall_deadline)
        if timeout is not None and timeout <= 0:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                process.kill()
            stdout, stderr = process.communicate()
            returncode = 124
            stderr = (stderr or "") + "\nworker skipped because launcher wall timeout expired"
            task.stdout_path.write_text(stdout or "", encoding="utf-8")
            task.stderr_path.write_text(stderr or "", encoding="utf-8")
            task.returncode_path.write_text(str(returncode) + "\n", encoding="utf-8")
            error = "launcher wall timeout expired"
            _write_failure_result(task, returncode, error, stdout, stderr)
            results.append(WorkerResult(task, returncode, False, str(task.result_path), error))
            continue
        try:
            stdout, stderr = process.communicate(
                input=_prompt_with_deadline(task.prompt, worker.return_deadline_epoch, float(args.return_slack)),
                timeout=timeout,
            )
            returncode = int(process.returncode or 0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                process.kill()
            stdout, stderr = process.communicate()
            returncode = 124
            stderr = (stderr or "") + f"\nworker timed out after {args.timeout}s"
        task.stdout_path.write_text(stdout or "", encoding="utf-8")
        task.stderr_path.write_text(stderr or "", encoding="utf-8")
        task.returncode_path.write_text(str(returncode) + "\n", encoding="utf-8")

        error = ""
        if not task.result_path.exists() and stdout and _looks_like_json(stdout):
            task.result_path.write_text(stdout.strip() + "\n", encoding="utf-8")
        if not task.result_path.exists():
            error = "worker did not write a result file"
            _write_failure_result(task, returncode, error, stdout, stderr)
        elif returncode != 0:
            error = f"worker exited {returncode}"
        results.append(WorkerResult(task, returncode, False, str(task.result_path), error))
    return results


def _wall_time_exhausted(wall_deadline: float | None) -> bool:
    return wall_deadline is not None and time.monotonic() >= wall_deadline


def _remaining_timeout(worker_timeout: float | None, wall_deadline: float | None) -> float | None:
    remaining_wall = None if wall_deadline is None else max(0.0, wall_deadline - time.monotonic())
    if worker_timeout is None:
        return remaining_wall
    if remaining_wall is None:
        return worker_timeout
    return min(float(worker_timeout), remaining_wall)


def _remaining_process_timeout(process_deadline: float | None, wall_deadline: float | None) -> float | None:
    remaining_process = None if process_deadline is None else max(0.0, process_deadline - time.monotonic())
    remaining_wall = None if wall_deadline is None else max(0.0, wall_deadline - time.monotonic())
    if remaining_process is None:
        return remaining_wall
    if remaining_wall is None:
        return remaining_process
    return min(remaining_process, remaining_wall)


def _return_deadline_epoch(worker_timeout: float | None, return_slack: float) -> float | None:
    if worker_timeout is None:
        return None
    timeout = max(0.0, float(worker_timeout))
    if timeout <= 0:
        return time.time()
    slack = max(0.0, float(return_slack))
    reserve = slack if timeout > slack else timeout / 2.0
    return time.time() + max(1.0, timeout - reserve)


def _format_epoch_utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _prompt_with_deadline(prompt: str, return_deadline_epoch: float | None, return_slack: float) -> str:
    if return_deadline_epoch is None:
        return prompt
    deadline = _format_epoch_utc(return_deadline_epoch)
    return (
        prompt.rstrip()
        + "\n\nTeamRun cooperative deadline:\n"
        + f"- Write the result JSON by {deadline} (epoch {return_deadline_epoch:.3f}).\n"
        + f"- Reserve the last {max(0.0, return_slack):.0f}s for summarizing claims/evidence.\n"
        + "- If exploration is incomplete, return a partial or exhausted result with the best task-visible claims and residual risk.\n"
    )


def _submit_results(
    statem_cmd: str,
    cwd: Path,
    state_dir: Path,
    run_id: str,
    entry_id: str,
    results: list[WorkerResult],
    agent_role: str,
) -> list[WorkerResult]:
    submitted: list[WorkerResult] = []
    for result in results:
        try:
            _statem_json(
                statem_cmd,
                cwd,
                state_dir,
                run_id,
                [
                    "team",
                    "submit",
                    result.task.task_id,
                    result.result_path,
                    "--entry-id",
                    entry_id,
                    "--agent-id",
                    result.task.agent_id,
                    "--agent-role",
                    agent_role,
                ],
            )
        except RuntimeError as exc:
            result.error = (result.error + "; " if result.error else "") + str(exc)
            submitted.append(result)
            continue
        result.submitted = True
        submitted.append(result)
    return submitted


def _submit_reports(
    statem_cmd: str,
    cwd: Path,
    state_dir: Path,
    run_id: str,
    entry_id: str,
    results: list[WorkerResult],
    agent_role: str,
) -> dict[str, int]:
    reported = 0
    errors = 0
    for result in results:
        report_path = result.task.report_path
        if not report_path.exists():
            continue
        try:
            _statem_json(
                statem_cmd,
                cwd,
                state_dir,
                run_id,
                [
                    "team",
                    "report",
                    result.task.task_id,
                    str(report_path),
                    "--entry-id",
                    entry_id,
                    "--agent-id",
                    result.task.agent_id,
                    "--agent-role",
                    agent_role,
                ],
            )
        except RuntimeError as exc:
            errors += 1
            result.error = (result.error + "; " if result.error else "") + f"report failed: {exc}"
            continue
        reported += 1
    return {"reported": reported, "errors": errors}


def _statem_json(statem_cmd: str, cwd: Path, state_dir: Path, run_id: str, args: list[str]) -> dict[str, Any]:
    argv = [*shlex.split(statem_cmd), *args, "--run-id", run_id, "--state-dir", str(state_dir), "--json"]
    completed = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"statem exited {completed.returncode}"
        raise RuntimeError(message)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"statem did not return JSON: {completed.stdout}") from exc


def _format_worker_command(command: str, task: ClaimedTask) -> str:
    return command.format(
        task_id=shlex.quote(task.task_id),
        prompt_file=shlex.quote(str(task.prompt_path)),
        result_file=shlex.quote(str(task.result_path)),
        report_file=shlex.quote(str(task.report_path)),
        work_dir=shlex.quote(str(task.work_dir)),
        assignment_file=shlex.quote(task.assignment_path),
    )


def _write_failure_result(task: ClaimedTask, returncode: int, error: str, stdout: str | None, stderr: str | None) -> None:
    payload = {
        "status": "failed",
        "summary": error,
        "claims": [],
        "evidence": [
            {
                "type": "worker_failure",
                "returncode": returncode,
                "stdout_path": str(task.stdout_path),
                "stderr_path": str(task.stderr_path),
                "stdout_tail": (stdout or "")[-2000:],
                "stderr_tail": (stderr or "")[-2000:],
            }
        ],
        "coverage": {"complete": False},
        "children": [],
        "prune_proposals": [],
    }
    task.result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") and stripped.endswith("}")


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"TeamRun workers: claimed={summary.get('claimed')} "
        f"reported={summary.get('reported')} submitted={summary.get('submitted')} "
        f"failed={summary.get('failed')}"
    )
    for round_entry in summary.get("rounds", []):
        print(f"- round {round_entry.get('round')}: {round_entry.get('claimed') or round_entry.get('reason') or round_entry.get('error')}")


def _emit_error(message: str) -> None:
    print(f"teamrun_worker_loop: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
