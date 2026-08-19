from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import artifact_identity, file_sha256, stable_sha256
except ImportError:
    from artifact_identity import (  # type: ignore[no-redef]
        artifact_identity,
        file_sha256,
        stable_sha256,
    )


DEFAULT_DIR = Path("/tmp/statem-verification-checks/multirole")
DEFAULT_PLAN = DEFAULT_DIR / "acceptance-replay-plan-draft.json"
DEFAULT_PROPOSAL = DEFAULT_DIR / "candidate-proposal.json"
DEFAULT_ACCEPTANCE = DEFAULT_DIR / "acceptance-evidence.json"
DEFAULT_SNAPSHOT = Path(
    "/tmp/statem-verification-checks/artifact-provider/candidate-snapshot.json"
)
DEFAULT_OUTPUT = DEFAULT_DIR / "acceptance-replay.json"
DEFAULT_WORK_ROOT = Path("/tmp/statem-verification-checks/acceptance-replay/work")

PLAN_FIELDS = {"candidate_artifact_identity", "checks"}
CHECK_FIELDS = {
    "check_id",
    "public_surface",
    "method",
    "argv",
    "cwd",
    "timeout_seconds",
    "expected_exit_codes",
}
CHECK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MAX_CHECKS = 4
MAX_TIMEOUT_SECONDS = 90
MAX_TOTAL_TIMEOUT_SECONDS = 180
MAX_ARGV_ITEMS = 32
MAX_ARG_CHARS = 512
MAX_ARGV_CHARS = 4096
MAX_TEXT_CHARS = 600
MAX_STREAM_BYTES = 64_000
POLL_SECONDS = 0.05
SENSITIVE_ENV_MARKERS = (
    "AUTH",
    "CREDENTIAL",
    "KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay bounded candidate acceptance checks on an immutable snapshot copy."
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--acceptance-evidence", type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument("--candidate-snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--artifact-root", type=Path, default=Path("/app"))
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        plan = _read_json(args.plan)
        proposal = _read_json(args.proposal)
        acceptance = _read_json(args.acceptance_evidence)
        snapshot = _read_json(args.candidate_snapshot)
        receipt = replay_acceptance_checks(
            plan=plan,
            proposal=proposal,
            acceptance_evidence=acceptance,
            candidate_snapshot=snapshot,
            artifact_root=args.artifact_root,
            work_root=args.work_root,
            existing_receipt=(
                _read_json(args.output) if args.output.is_file() else None
            ),
        )
        _write_json(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def replay_acceptance_checks(
    *,
    plan: dict[str, Any],
    proposal: dict[str, Any],
    acceptance_evidence: dict[str, Any],
    candidate_snapshot: dict[str, Any],
    artifact_root: Path,
    work_root: Path,
    existing_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(proposal, "candidate_proposal")
    _require_receipt(acceptance_evidence, "candidate_bound_acceptance_evidence")
    _require_receipt(candidate_snapshot, "filesystem_artifact_snapshot")
    context = _state_context()
    if context["node"] not in {"solve", "revise"}:
        raise ValueError("candidate acceptance replay belongs to solve or revise")
    for label, receipt in (
        ("proposal", proposal),
        ("acceptance evidence", acceptance_evidence),
        ("candidate snapshot", candidate_snapshot),
    ):
        if receipt.get("run_id") != context["run_id"]:
            raise ValueError(f"{label} belongs to another StateM run")
        if receipt.get("entry_id") != context["entry_id"]:
            raise ValueError(f"{label} belongs to another StateM entry")

    proposal_sha256 = stable_sha256(proposal)
    snapshot_sha256 = stable_sha256(candidate_snapshot)
    acceptance_sha256 = stable_sha256(acceptance_evidence)
    candidate_identity = _text(proposal.get("candidate_artifact_identity"))
    if not candidate_identity:
        raise ValueError("candidate proposal is missing its artifact identity")
    if candidate_snapshot.get("snapshot_kind") != "candidate":
        raise ValueError("candidate acceptance replay requires a candidate snapshot")
    if candidate_snapshot.get("artifact_identity") != candidate_identity:
        raise ValueError("candidate snapshot is bound to another artifact")
    if candidate_snapshot.get("expected_receipt_sha256") != proposal_sha256:
        raise ValueError("candidate snapshot is not bound to the current proposal")
    if acceptance_evidence.get("proposal_sha256") != proposal_sha256:
        raise ValueError("acceptance evidence is not bound to the current proposal")
    if acceptance_evidence.get("candidate_snapshot_sha256") != snapshot_sha256:
        raise ValueError("acceptance evidence is not bound to the current snapshot")
    if acceptance_evidence.get("candidate_artifact_identity") != candidate_identity:
        raise ValueError("acceptance evidence is bound to another artifact")

    normalized_plan = _normalize_plan(plan, candidate_identity)
    _reject_sensitive_values(normalized_plan)
    plan_sha256 = stable_sha256(normalized_plan)
    bindings = {
        "proposal_sha256": proposal_sha256,
        "acceptance_evidence_sha256": acceptance_sha256,
        "candidate_snapshot_sha256": snapshot_sha256,
        "candidate_artifact_identity": candidate_identity,
        "plan_sha256": plan_sha256,
    }

    artifact_root = artifact_root.expanduser().resolve()
    snapshot_root = Path(_text(candidate_snapshot.get("snapshot_path"))).expanduser().resolve()
    if not snapshot_root.is_dir():
        raise ValueError("candidate snapshot path is missing")
    if artifact_identity(snapshot_root) != candidate_identity:
        raise ValueError("immutable candidate snapshot identity changed")
    if artifact_identity(artifact_root) != candidate_identity:
        raise ValueError("live artifact no longer matches the candidate snapshot")
    if existing_receipt is not None and _receipt_reusable(
        existing_receipt, context=context, bindings=bindings
    ):
        return existing_receipt

    work_root = work_root.expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    for check in normalized_plan["checks"]:
        remaining = MAX_TOTAL_TIMEOUT_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            results.append(_not_run_result(check, "total_budget_exhausted"))
            continue
        effective_timeout = min(float(check["timeout_seconds"]), remaining)
        with tempfile.TemporaryDirectory(
            prefix=f"{check['check_id']}-", dir=str(work_root)
        ) as temporary:
            temporary_root = Path(temporary)
            replay_root = temporary_root / "candidate"
            shutil.copytree(snapshot_root, replay_root, symlinks=True)
            _make_owner_writable(replay_root)
            if artifact_identity(replay_root) != candidate_identity:
                raise ValueError("replay copy differs from the immutable candidate snapshot")
            results.append(
                _run_check(
                    check,
                    replay_root=replay_root,
                    scratch_root=temporary_root,
                    timeout_seconds=effective_timeout,
                )
            )
        if artifact_identity(snapshot_root) != candidate_identity:
            raise ValueError("acceptance replay mutated the immutable snapshot")
        if artifact_identity(artifact_root) != candidate_identity:
            raise ValueError("acceptance replay mutated the live candidate")

    execution_complete = all(
        result["status"] != "not_run_budget" for result in results
    )
    all_passed = execution_complete and all(
        result["status"] == "passed" for result in results
    )
    return {
        "version": 1,
        "kind": "candidate_acceptance_replay",
        **context,
        "producer": {
            "agent_id": f"acceptance-replay:{context['run_id']}:{context['entry_id']}",
            "role": "acceptance_replay_adapter",
        },
        "attestation_scope": "adapter_executed_snapshot_copy",
        **bindings,
        "candidate_snapshot_identity": candidate_snapshot.get("snapshot_identity"),
        "plan": normalized_plan,
        "limits": {
            "checks": MAX_CHECKS,
            "per_check_timeout_seconds": MAX_TIMEOUT_SECONDS,
            "total_timeout_seconds": MAX_TOTAL_TIMEOUT_SECONDS,
            "stream_bytes": MAX_STREAM_BYTES,
        },
        "environment_policy": "minimal_allowlist_no_solver_credentials",
        "workspace_policy": "fresh_disposable_copy_per_check",
        "execution_complete": execution_complete,
        "all_passed": all_passed,
        "overall_status": (
            "passed" if all_passed else "failed" if execution_complete else "incomplete"
        ),
        "results": results,
        "live_artifact_identity_after": artifact_identity(artifact_root),
        "snapshot_identity_after": artifact_identity(snapshot_root),
        "created_at": _now(),
    }


def _normalize_plan(plan: dict[str, Any], candidate_identity: str) -> dict[str, Any]:
    if set(plan) != PLAN_FIELDS:
        raise ValueError("acceptance replay plan requires exactly candidate_artifact_identity and checks")
    if plan.get("candidate_artifact_identity") != candidate_identity:
        raise ValueError("acceptance replay plan is bound to another candidate")
    checks = plan.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) > MAX_CHECKS:
        raise ValueError(f"acceptance replay plan requires 1-{MAX_CHECKS} checks")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_timeout = 0
    for index, raw in enumerate(checks):
        if not isinstance(raw, dict) or set(raw) != CHECK_FIELDS:
            raise ValueError(f"acceptance replay check {index} has an invalid schema")
        check_id = _text(raw.get("check_id"))
        if not CHECK_ID.fullmatch(check_id) or check_id in seen:
            raise ValueError(f"acceptance replay check {index} has an invalid or duplicate id")
        seen.add(check_id)
        public_surface = _bounded_text(raw.get("public_surface"), "public_surface")
        method = _bounded_text(raw.get("method"), "method")
        argv = raw.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > MAX_ARGV_ITEMS
            or not all(isinstance(item, str) and item and "\x00" not in item for item in argv)
        ):
            raise ValueError(f"acceptance replay check {check_id} has invalid argv")
        if any(len(item) > MAX_ARG_CHARS for item in argv) or sum(map(len, argv)) > MAX_ARGV_CHARS:
            raise ValueError(f"acceptance replay check {check_id} argv exceeds its budget")
        cwd = _text(raw.get("cwd")) or "."
        cwd_path = Path(cwd)
        if cwd_path.is_absolute() or ".." in cwd_path.parts:
            raise ValueError(f"acceptance replay check {check_id} cwd must stay inside the snapshot")
        timeout_seconds = raw.get("timeout_seconds")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds < 1
            or timeout_seconds > MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(f"acceptance replay check {check_id} timeout is invalid")
        total_timeout += timeout_seconds
        exit_codes = raw.get("expected_exit_codes")
        if (
            not isinstance(exit_codes, list)
            or not exit_codes
            or len(exit_codes) > 4
            or not all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= 255
                for value in exit_codes
            )
        ):
            raise ValueError(f"acceptance replay check {check_id} exit codes are invalid")
        normalized.append(
            {
                "check_id": check_id,
                "public_surface": public_surface,
                "method": method,
                "argv": list(argv),
                "cwd": cwd_path.as_posix(),
                "timeout_seconds": timeout_seconds,
                "expected_exit_codes": sorted(set(exit_codes)),
            }
        )
    if total_timeout > MAX_TOTAL_TIMEOUT_SECONDS:
        raise ValueError("acceptance replay plan exceeds the total timeout budget")
    return {
        "candidate_artifact_identity": candidate_identity,
        "checks": normalized,
    }


def _run_check(
    check: dict[str, Any],
    *,
    replay_root: Path,
    scratch_root: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    cwd = (replay_root / check["cwd"]).resolve()
    if not cwd.is_relative_to(replay_root) or not cwd.is_dir():
        return _not_run_result(check, "cwd_missing")
    stdout_path = scratch_root / "stdout.bin"
    stderr_path = scratch_root / "stderr.bin"
    env = _minimal_environment(replay_root, scratch_root)
    started = time.monotonic()
    status = "launch_error"
    returncode: int | None = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            process = subprocess.Popen(
                check["argv"],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except OSError:
            process = None
        if process is not None:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= timeout_seconds:
                    status = "timed_out"
                    _terminate_process_group(process)
                    break
                if _file_size(stdout_path) > MAX_STREAM_BYTES or _file_size(stderr_path) > MAX_STREAM_BYTES:
                    status = "output_limit"
                    _terminate_process_group(process)
                    break
                time.sleep(POLL_SECONDS)
            if process.poll() is None:
                _terminate_process_group(process)
            returncode = process.wait()
            _cleanup_process_group(process.pid)
            if (
                status != "timed_out"
                and (
                    _file_size(stdout_path) > MAX_STREAM_BYTES
                    or _file_size(stderr_path) > MAX_STREAM_BYTES
                )
            ):
                status = "output_limit"
            elif status not in {"timed_out", "output_limit"}:
                status = (
                    "passed"
                    if returncode in check["expected_exit_codes"]
                    else "failed"
                )
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "check_id": check["check_id"],
        "public_surface": check["public_surface"],
        "method": check["method"],
        "command_sha256": stable_sha256(check["argv"]),
        "cwd": check["cwd"],
        "timeout_seconds": check["timeout_seconds"],
        "expected_exit_codes": check["expected_exit_codes"],
        "status": status,
        "observed_exit_code": returncode,
        "duration_ms": duration_ms,
        "stdout_bytes": _file_size(stdout_path),
        "stdout_sha256": file_sha256(stdout_path),
        "stderr_bytes": _file_size(stderr_path),
        "stderr_sha256": file_sha256(stderr_path),
    }


def _not_run_result(check: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "check_id": check["check_id"],
        "public_surface": check["public_surface"],
        "method": check["method"],
        "command_sha256": stable_sha256(check["argv"]),
        "cwd": check["cwd"],
        "timeout_seconds": check["timeout_seconds"],
        "expected_exit_codes": check["expected_exit_codes"],
        "status": "not_run_budget",
        "reason": reason,
        "observed_exit_code": None,
        "duration_ms": 0,
        "stdout_bytes": 0,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
    }


def _minimal_environment(replay_root: Path, scratch_root: Path) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(scratch_root / "home"),
        "TMPDIR": str(scratch_root / "tmp"),
        "PYTHONNOUSERSITE": "1",
        "STATEM_CANDIDATE_ROOT": str(replay_root),
    }
    for key in ("LANG", "LC_ALL", "TZ"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(environment["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return environment


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass


def _cleanup_process_group(pid: int) -> None:
    """Stop descendants that outlive a successful group leader."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (PermissionError, ProcessLookupError):
        return
    time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (PermissionError, ProcessLookupError):
        pass


def _make_owner_writable(root: Path) -> None:
    for path in [root, *sorted(root.rglob("*"))]:
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR)


def _receipt_reusable(
    receipt: dict[str, Any],
    *,
    context: dict[str, str],
    bindings: dict[str, str],
) -> bool:
    return (
        receipt.get("kind") == "candidate_acceptance_replay"
        and all(receipt.get(key) == value for key, value in context.items())
        and all(receipt.get(key) == value for key, value in bindings.items())
    )


def _reject_sensitive_values(value: Any) -> None:
    encoded = json.dumps(value, sort_keys=True)
    for key, secret in os.environ.items():
        if (
            any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS)
            and len(secret) >= 8
            and secret in encoded
        ):
            raise ValueError("acceptance replay plan contains a sensitive environment value")


def _state_context() -> dict[str, str]:
    run_id = _text(os.environ.get("STATEM_RUN_ID"))
    state_dir = Path(os.environ.get("STATEM_STATE_DIR") or ".statem").expanduser().resolve()
    state: dict[str, Any] = {}
    if run_id:
        for candidate in (state_dir / "runs").glob("*/state.json"):
            try:
                value = _read_json(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if value.get("run_id") == run_id:
                state = value
                break
    context = {
        "run_id": run_id or _text(state.get("run_id")),
        "node": _text(state.get("current") or os.environ.get("STATEM_CURRENT")),
        "entry_id": _text(
            state.get("current_entry_id") or os.environ.get("STATEM_ENTRY_ID")
        ),
    }
    if not all(context.values()):
        raise ValueError("StateM run, node, and entry identity are required")
    return context


def _require_receipt(value: dict[str, Any], kind: str) -> None:
    if not isinstance(value, dict) or value.get("kind") != kind:
        raise ValueError(f"expected {kind} receipt")


def _bounded_text(value: Any, field: str) -> str:
    text = _text(value)
    if not text or len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"acceptance replay {field} must contain 1-{MAX_TEXT_CHARS} characters")
    return text


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
