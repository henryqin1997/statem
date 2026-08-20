#!/usr/bin/env python3
"""Run one Codex subagent for a leased statem TeamRun task.

This script is intended to be used as the worker command for
`teamrun_worker_loop.py`. It receives the scoped TeamRun prompt via
environment variables, launches `codex exec`, and normalizes the worker's
result JSON so the outer loop can submit it through `statem team submit`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    prompt_file = Path(args.prompt_file or os.environ.get("STATEM_TEAM_PROMPT_FILE", "")).expanduser()
    result_file = Path(args.result_file or os.environ.get("STATEM_TEAM_RESULT_FILE", "")).expanduser()
    assignment_file = Path(args.assignment_file or os.environ.get("STATEM_TEAM_ASSIGNMENT_FILE", "")).expanduser()
    task_id = args.task_id or os.environ.get("STATEM_TEAM_TASK_ID", "")
    agent_id = args.agent_id or os.environ.get("STATEM_TEAM_AGENT_ID", "")
    agent_role = args.agent_role or os.environ.get("STATEM_TEAM_AGENT_ROLE", "team-worker")
    report_file = Path(os.environ.get("STATEM_TEAM_REPORT_FILE", "")).expanduser()
    work_dir = Path(os.environ.get("STATEM_TEAM_WORK_DIR", "")).expanduser()

    if not prompt_file.is_file():
        _emit_error(f"prompt file not found: {prompt_file}")
        return 1
    if not result_file:
        _emit_error("result file path is required")
        return 1

    result_file.parent.mkdir(parents=True, exist_ok=True)
    prompt = prompt_file.read_text(encoding="utf-8")
    instruction = _build_instruction(
        prompt=prompt,
        result_file=result_file,
        assignment_file=assignment_file,
        task_id=task_id,
        agent_id=agent_id,
        agent_role=agent_role,
        report_file=report_file,
        work_dir=work_dir,
        execution_profile=args.execution_profile,
    )
    output_file: Path | None = None
    if args.execution_profile == "read-only-review":
        output_file = result_file
    completed = _run_codex(
        args,
        instruction,
        schema_file=None,
        output_file=output_file,
    )

    payload: dict[str, Any] | None = None
    if result_file.exists():
        payload = _load_result(result_file)
    if payload is None:
        payload = _extract_json_payload(completed.stdout)
    if payload is None:
        payload = _failure_payload(
            task_id=task_id,
            agent_id=agent_id,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            message="codex worker did not write a parseable TeamRun result JSON",
        )
        result_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _emit_error(payload["summary"])
        return completed.returncode or 1

    normalized = _normalize_result_payload(payload, completed.returncode, completed.stdout, completed.stderr)
    result_file.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"teamrun_codex_worker: wrote {result_file}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Codex TeamRun worker for one scoped task.")
    parser.add_argument("--codex-command", default=os.environ.get("STATEM_CODEX_COMMAND", "codex"))
    parser.add_argument("--model", default=os.environ.get("STATEM_CODEX_MODEL", "gpt-5.5"))
    parser.add_argument("--reasoning-effort", default=os.environ.get("STATEM_CODEX_REASONING_EFFORT", "high"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--prompt-file")
    parser.add_argument("--result-file")
    parser.add_argument("--assignment-file")
    parser.add_argument("--task-id")
    parser.add_argument("--agent-id")
    parser.add_argument("--agent-role", default=os.environ.get("STATEM_TEAM_AGENT_ROLE", "team-worker"))
    parser.add_argument(
        "--execution-profile",
        choices=("default", "read-only-review"),
        default="default",
    )
    parser.add_argument("--extra-codex-arg", action="append", default=[])
    parser.add_argument("--no-bypass", action="store_true", help="do not pass Codex bypass/sandbox flags")
    parser.add_argument("--no-unified-exec", action="store_true", help="do not pass --enable unified_exec")
    return parser


def _build_instruction(
    *,
    prompt: str,
    result_file: Path,
    assignment_file: Path,
    task_id: str,
    agent_id: str,
    agent_role: str,
    report_file: Path,
    work_dir: Path,
    execution_profile: str,
) -> str:
    if execution_profile == "read-only-review":
        scope_delivery = (
            "Work only on the scoped task below. Do not advance the global StateM run, "
            "call StateM mutation commands, inspect sibling TeamRun state, or edit any "
            "artifact. The scoped assignment contains a trusted read-only context bundle. "
            "Use only that embedded bundle and do not call tools, commands, or filesystem "
            "APIs. If the bundle is incomplete, return an honest partial or inconclusive "
            "result instead of attempting external inspection."
        )
        result_delivery = (
            "Your execution sandbox is read-only. Do not edit the task artifact, "
            "StateM state, reports, or scratch files. Return exactly one JSON object "
            "matching the required result shape as your final response; the trusted "
            "outer launcher will validate and record it under your leased StateM identity. "
            "Include every additional top-level field required by the scoped assignment."
        )
        scratch_delivery = (
            "Do not create intermediate artifacts; keep compact evidence in the final JSON."
        )
        progress_delivery = (
            "Do not write an interim report. Put the best complete or partial evidence "
            "in the final JSON before the cooperative deadline."
        )
    else:
        scope_delivery = (
            "Work only on the scoped task below. Do not advance the global statem run, "
            "do not call `statem team submit`, and do not edit sibling TeamRun state. "
            "Do not edit the final task artifact unless this scoped assignment explicitly "
            "asks for that. You may inspect task-visible files and create local evidence "
            "artifacts if they help."
        )
        result_delivery = f"Write your TeamRun result JSON to:\n{result_file}"
        scratch_delivery = (
            f"Use this isolated scratch directory for intermediate artifacts:\n{work_dir}"
        )
        progress_delivery = f"""If you need to make stage-visible progress before the final result, write a
report JSON draft to:
{report_file}

For bounded searches, write an early report as soon as you have a credible
candidate, rejected candidate, or narrowed search interval. Then continue
refining if time remains. The host may append this report to the parent
TeamRun before your final result if you time out."""
    return f"""You are a statem TeamRun subagent.

{scope_delivery}

{result_delivery}

{scratch_delivery}

{progress_delivery}

Required result shape:
{{
  "status": "completed|terminal|expanded|exhausted|failed|blocked|partial",
  "summary": "compact attention index for the lead agent",
  "claims": [],
  "evidence": [],
  "coverage": {{"complete": true}},
  "children": [],
  "prune_proposals": []
}}

{_deadline_instruction()}

If you are uncertain, still write a partial result with `coverage.complete`
false and explain the residual risk in `summary` and `evidence`.

Put every substantive conclusion in `claims`; `evidence` is only supporting
material. If this scoped search finds no candidate, use status `exhausted` with
`coverage.complete=true` instead of a completed result with empty claims.

Metadata:
- task_id: {task_id}
- agent_id: {agent_id}
- agent_role: {agent_role}
- assignment_file: {assignment_file}

Scoped worker prompt:
{prompt}
"""


def _deadline_instruction() -> str:
    deadline = os.environ.get("STATEM_TEAM_RETURN_DEADLINE") or ""
    deadline_epoch = os.environ.get("STATEM_TEAM_RETURN_DEADLINE_EPOCH") or ""
    slack = os.environ.get("STATEM_TEAM_RETURN_SLACK_SECONDS") or ""
    timeout = os.environ.get("STATEM_TEAM_WORKER_TIMEOUT_SECONDS") or ""
    if not deadline and not deadline_epoch:
        return "Cooperative deadline: no explicit return deadline was provided."
    pieces = [
        "Cooperative deadline:",
        f"- worker hard timeout budget: {timeout or '(unknown)'} seconds",
        f"- write the result JSON by: {deadline or deadline_epoch}",
    ]
    if deadline_epoch and deadline:
        pieces[-1] += f" (epoch {deadline_epoch})"
    pieces.extend(
        [
            f"- reserve the last {slack or 'several'} seconds for summarizing claims/evidence",
            "- when the deadline is near, stop exploration and return the best partial/exhausted result instead of waiting for a hard kill",
        ]
    )
    return "\n".join(pieces)


def _run_codex(
    args: argparse.Namespace,
    instruction: str,
    *,
    schema_file: Path | None = None,
    output_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [*shlex.split(args.codex_command), "exec"]
    if args.execution_profile == "read-only-review":
        argv.extend(
            [
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
            ]
        )
        if output_file is not None:
            argv.extend(["--output-last-message", str(output_file)])
    elif not args.no_bypass:
        argv.extend(["--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"])
    if not args.no_unified_exec:
        argv.extend(["--enable", "unified_exec"])
    if args.model:
        argv.extend(["--model", args.model])
    if args.reasoning_effort:
        argv.extend(["-c", f"model_reasoning_effort={args.reasoning_effort}"])
    for extra in args.extra_codex_arg:
        argv.extend(shlex.split(extra))
    # Codex accepts `-` as a prompt sentinel. Keep the bounded assignment off
    # argv so reviewer context is governed by StateM's content budget rather
    # than the host's much smaller and platform-dependent ARG_MAX.
    argv.extend(["--", "-"])
    return subprocess.run(
        argv,
        cwd=Path(args.cwd).expanduser(),
        text=True,
        input=instruction,
        capture_output=True,
        check=False,
        env=_codex_child_env(args),
    )


def _codex_child_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "STATEM_RUN_ID",
        "STATEM_ENTRY_ID",
        "STATEM_STATE_DIR",
        "STATEM_COMMAND",
        "STATEM_DEADLINE_FILE",
        "STATEM_RUNTIME_ANCHOR_FILE",
        "STATEM_AGENT_ID",
        "STATEM_AGENT_ROLE",
    ):
        env.pop(key, None)
    if args.prompt_file:
        env["STATEM_TEAM_PROMPT_FILE"] = args.prompt_file
    if args.result_file:
        env["STATEM_TEAM_RESULT_FILE"] = args.result_file
    if args.assignment_file:
        env["STATEM_TEAM_ASSIGNMENT_FILE"] = args.assignment_file
    if args.task_id:
        env["STATEM_TEAM_TASK_ID"] = args.task_id
    if args.agent_id:
        env["STATEM_TEAM_AGENT_ID"] = args.agent_id
    if args.agent_role:
        env["STATEM_TEAM_AGENT_ROLE"] = args.agent_role
    env["STATEM_TEAM_WORKER_SCOPE"] = "scoped_result_only"
    return env


def _result_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": [
            "status",
            "summary",
            "claims",
            "evidence",
            "coverage",
            "children",
            "prune_proposals",
        ],
        "properties": {
            "status": {
                "type": "string",
                "enum": [
                    "completed",
                    "terminal",
                    "expanded",
                    "exhausted",
                    "failed",
                    "blocked",
                    "partial",
                ],
            },
            "summary": {"type": "string"},
            "claims": {"type": "array"},
            "evidence": {"type": "array"},
            "coverage": {"type": "object"},
            "children": {"type": "array"},
            "prune_proposals": {"type": "array"},
        },
        "additionalProperties": True,
    }


def _load_result(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    if "```" in stripped:
        parts = stripped.split("```")
        candidates.extend(part.strip().removeprefix("json").strip() for part in parts)
    start = stripped.rfind("{")
    end = stripped.rfind("}")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _normalize_result_payload(
    payload: dict[str, Any],
    returncode: int,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    allowed = {"completed", "terminal", "expanded", "exhausted", "failed", "blocked", "partial"}
    normalized = dict(payload)
    status = str(normalized.get("status") or "completed")
    normalized["status"] = status if status in allowed else "partial"
    normalized["summary"] = str(normalized.get("summary") or "Codex subagent completed the scoped task.")
    for key in ("claims", "evidence", "children", "prune_proposals"):
        if not isinstance(normalized.get(key), list):
            normalized[key] = []
    if not isinstance(normalized.get("coverage"), dict):
        normalized["coverage"] = {"complete": normalized["status"] in {"completed", "terminal"}}
    if returncode != 0:
        normalized["evidence"].append(
            {
                "type": "codex_worker_returncode",
                "returncode": returncode,
                "stdout_tail": stdout[-1200:],
                "stderr_tail": stderr[-1200:],
            }
        )
        if normalized["status"] == "completed":
            normalized["status"] = "partial"
            normalized["coverage"]["complete"] = False
    return normalized


def _failure_payload(
    *,
    task_id: str,
    agent_id: str,
    returncode: int,
    stdout: str,
    stderr: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "summary": message,
        "claims": [],
        "evidence": [
            {
                "type": "codex_worker_failure",
                "task_id": task_id,
                "agent_id": agent_id,
                "returncode": returncode,
                "stdout_tail": stdout[-2000:],
                "stderr_tail": stderr[-2000:],
            }
        ],
        "coverage": {"complete": False},
        "children": [],
        "prune_proposals": [],
    }


def _emit_error(message: str) -> None:
    print(f"teamrun_codex_worker: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
