from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import time
from pathlib import Path
from typing import Any

from . import miniyaml

TEAM_PURPOSE = "multi_agent"
TEAM_PHASES = {"divided", "exploring", "reducing", "decided", "blocked"}
TEAM_CLOSED_TASK_STATUSES = {
    "completed",
    "terminal",
    "expanded",
    "exhausted",
    "failed",
    "blocked",
    "partial",
    "pruned",
}

TEAM_BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "video_segment_scan_v1": {
        "required": ["task_id", "input.video", "input.start_frame", "input.end_frame"],
        "types": {
            "task_id": "string",
            "input.video": "string",
            "input.start_frame": "integer",
            "input.end_frame": "integer",
        },
    },
    "takeoff_candidate_v1": {
        "required": ["status", "summary", "claims", "evidence", "coverage"],
        "types": {
            "status": "string",
            "claims": "list",
            "evidence": "list",
            "coverage": "mapping",
        },
    },
}


def _statem_error(message: str, *, details: dict[str, Any] | None = None) -> Exception:
    from .core import StatemError

    return StatemError(message, details=details)


def validate_team_config(raw_config: Any, label: str) -> list[str]:
    try:
        config = _normalize_team_config(raw_config)
    except (Exception, ValueError) as exc:
        return [f"{label}: {exc}"]
    if not config:
        return []
    errors: list[str] = []
    if config["max_parallel"] < 0:
        errors.append(f"{label}: max_parallel cannot be negative")
    if config["mode"] not in {"fanout_reduce", "fanout_search_reduce"}:
        errors.append(f"{label}: mode must be 'fanout_reduce' or 'fanout_search_reduce'")
    reducer = config.get("reducer") or {}
    if reducer:
        strategy = str(reducer.get("strategy") or "all-claims-table")
        if strategy not in {"earliest-candidate", "highest-confidence", "all-claims-table", "coverage-required"}:
            errors.append(f"{label}: reducer.strategy is unsupported: {strategy}")
    for key in ("task_schema", "result_schema"):
        if key in config:
            try:
                _normalize_team_schema(config[key])
            except Exception as exc:
                errors.append(f"{label}: {key}: {exc}")
    return errors


def team_summary(raw_config: Any, path: Path | None) -> dict[str, Any] | None:
    config = _normalize_team_config(raw_config)
    if not config:
        return None
    summary: dict[str, Any] = {
        "mode": config["mode"],
        "max_parallel": config["max_parallel"],
        "required": config["required"],
        "require_all_tasks_done": config["require_all_tasks_done"],
        "reducer": config.get("reducer", {}),
    }
    if "task_schema" in config:
        summary["task_schema"] = config["task_schema"]
    if "result_schema" in config:
        summary["result_schema"] = config["result_schema"]
    if path is not None:
        summary["resolved_path"] = str(path)
    return summary


def team_dir(state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str) -> Path:
    return (
        state_dir
        / "runs"
        / _clean_run_id(str(state["run_id"]))
        / "nodes"
        / _clean_node_id(node_name)
        / entry_id
        / TEAM_PURPOSE
    )


def run_team_before_transfer(runtime: Any, spec: Any, state: dict[str, Any], source: str, target: str) -> dict[str, Any]:
    config = _normalize_team_config(spec.nodes[source].get(TEAM_PURPOSE))
    if not config:
        return {"configured": False, "results": []}
    if not config.get("required", True):
        return {"configured": True, "required": False, "results": []}

    entry_id = str(state.get("current_entry_id") or "")
    directory = team_dir(runtime.state_dir, state, source, entry_id)
    manifest_path = _team_manifest_path(runtime.state_dir, state, source, entry_id)
    results: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    if not manifest_path.exists():
        results.append(
            _team_gate_result(
                False,
                output=f"{TEAM_PURPOSE} requires an initialized TeamRun in {directory}",
            )
        )
    else:
        manifest = _read_json(manifest_path)
        changed = _refresh_team_leases(manifest)
        if changed:
            _write_team_manifest(runtime.state_dir, state, source, entry_id, manifest)
        phase = str(manifest.get("phase") or "")
        decision_path = str(manifest.get("decision_path") or "")
        problems: list[str] = []
        if phase != "decided":
            problems.append(f"TeamRun phase must be decided before leaving '{source}', got {phase!r}")
        if not decision_path:
            problems.append("TeamRun decision_path is missing")
        elif not Path(decision_path).exists():
            problems.append(f"TeamRun decision file is missing: {decision_path}")
        results.append(
            _team_gate_result(
                not problems,
                output="; ".join(problems) if problems else f"TeamRun decided for entry {entry_id}",
            )
        )

    payload = {
        "configured": True,
        "required": True,
        "path": str(directory),
        "entry_id": entry_id,
        "phase": manifest.get("phase") if manifest else None,
        "counts": _team_counts(manifest) if manifest else {},
        "decision_path": manifest.get("decision_path") if manifest else None,
        "results": results,
    }
    _append_event(state, TEAM_PURPOSE, {"node": source, "to": target, **payload})
    return payload


class TeamRunRuntime:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.options = runtime.options
        self.state_dir = runtime.state_dir

    def init(self, tasks_file: str, *, run_id: str | None = None, entry_id: str | None = None) -> dict[str, Any]:
        spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        directory = team_dir(self.state_dir, state, current, checked_entry_id)
        source_path = Path(tasks_file).expanduser().resolve()
        payload = _load_team_file(source_path)
        config = _normalize_team_config(spec.nodes[current].get(TEAM_PURPOSE))
        assignments = _normalize_team_assignments(payload)
        if not assignments:
            raise _statem_error("TeamRun requires at least one task")
        _validate_team_assignments(assignments, config.get("task_schema"))

        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest_path = _team_manifest_path(self.state_dir, state, current, checked_entry_id)
            if manifest_path.exists():
                raise _statem_error(f"TeamRun already exists for entry {checked_entry_id}; use 'statem team status'")

            created_at = _now()
            directory.mkdir(parents=True, exist_ok=True)
            tasks: dict[str, dict[str, Any]] = {}
            for assignment in assignments:
                task_id = assignment["task_id"]
                assignment_path = _team_assignment_path(self.state_dir, state, current, checked_entry_id, task_id)
                if assignment_path.exists():
                    raise _statem_error(f"Team task assignment already exists: {task_id}")
                assignment_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json(
                    assignment_path,
                    {
                        "version": 1,
                        "run_id": state["run_id"],
                        "node": current,
                        "entry_id": checked_entry_id,
                        "task_id": task_id,
                        "parent_id": assignment.get("parent_id"),
                        "depth": assignment.get("depth", 0),
                        "created_at": created_at,
                        "assignment": assignment["assignment"],
                    },
                )
                tasks[task_id] = _new_team_task_record(
                    task_id,
                    parent_id=assignment.get("parent_id"),
                    depth=int(assignment.get("depth") or 0),
                    priority=assignment.get("priority"),
                    assignment_path=str(assignment_path),
                    created_at=created_at,
                )

            manifest = {
                "version": 1,
                "run_id": state["run_id"],
                "node": current,
                "entry_id": checked_entry_id,
                "phase": "divided",
                "created_at": created_at,
                "updated_at": created_at,
                "config": config,
                "source_path": str(source_path),
                "tasks": tasks,
                "prune_proposals": [],
                "history": [{"ts": created_at, "event": "init", "tasks": len(tasks)}],
            }
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            _append_event(state, "team_init", {"node": current, "entry_id": checked_entry_id, "tasks": len(tasks), "path": str(directory)})
            self.runtime._write_state(state)
            return self._status_payload(state, current, checked_entry_id, manifest, include_results=False)

    def status(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        include_results: bool = False,
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            changed = _refresh_team_leases(manifest)
            if changed:
                _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            return self._status_payload(state, current, checked_entry_id, manifest, include_results=include_results)

    def prompt(
        self,
        task_id: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        command: str = "statem",
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        manifest = self._load_manifest(state, current, checked_entry_id)
        normalized_task_id = _clean_task_id(task_id)
        task = (manifest.get("tasks") or {}).get(normalized_task_id)
        if not task:
            raise _statem_error(f"Unknown TeamRun task: {normalized_task_id}")
        assignment = _read_json(Path(str(task["assignment_path"])))
        state_dir_arg = shlex.quote(str(self.state_dir))
        run_id_arg = shlex.quote(str(state["run_id"]))
        entry_arg = shlex.quote(checked_entry_id)
        task_arg = shlex.quote(normalized_task_id)
        work_dir = _team_work_dir(self.state_dir, state, current, checked_entry_id, normalized_task_id, "your-agent-id")
        prompt = f"""You are a statem TeamRun worker.

Work only on this leased task. Do not advance the global statem run and do not edit sibling task state.

Context:
- run_id: {state["run_id"]}
- node: {current}
- entry_id: {checked_entry_id}
- task_id: {normalized_task_id}
- team phase: {manifest.get("phase")}
- isolated work dir pattern: {work_dir}

Assignment JSON:
{json.dumps(assignment, indent=2, sort_keys=True)}

Return a result file with this shape:
{{
  "status": "completed|terminal|expanded|exhausted|failed|blocked|partial",
  "summary": "compact attention index for the lead",
  "claims": [],
  "evidence": [],
  "coverage": {{}},
  "children": [],
  "prune_proposals": []
}}

Put each substantive conclusion in `claims`; `evidence` only supports those
claims. Use status `exhausted` with `coverage.complete=true` when this scope was
searched and contains no candidate.

Append a stage-visible partial report without closing the task with:
{command} team report {task_arg} REPORT_FILE --run-id {run_id_arg} --state-dir {state_dir_arg} --entry-id {entry_arg} --agent-id <your-agent-id> --json

Submit with:
{command} team submit {task_arg} RESULT_FILE --run-id {run_id_arg} --state-dir {state_dir_arg} --entry-id {entry_arg} --agent-id <your-agent-id> --json
"""
        return {
            "run_id": state["run_id"],
            "current": current,
            "current_entry_id": checked_entry_id,
            "task_id": normalized_task_id,
            "assignment": assignment,
            "prompt": prompt.strip() + "\n",
        }

    def claim(
        self,
        task_id: str | None = None,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        lease_seconds: int = 3600,
        worker_index: int | None = None,
        worker_count: int | None = None,
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        agent_id = self.runtime._ensure_agent_identity(state)
        shard = _normalize_claim_shard(worker_index, worker_count)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") not in {"divided", "exploring"}:
                raise _statem_error(f"Cannot claim tasks while TeamRun phase is {manifest.get('phase')!r}")
            _refresh_team_leases(manifest)

            config = manifest.get("config") or {}
            max_parallel = int(config.get("max_parallel") or 0)
            active_leases = [task for task in (manifest.get("tasks") or {}).values() if task.get("status") == "leased"]
            if max_parallel and len(active_leases) >= max_parallel:
                raise _statem_error(f"TeamRun max_parallel={max_parallel} already has {len(active_leases)} active lease(s)")

            selected_task_id = _clean_task_id(task_id) if task_id else _select_open_team_task(manifest, shard=shard)
            if not selected_task_id:
                raise _statem_error("No open TeamRun tasks are available to claim")
            tasks = manifest.get("tasks") or {}
            task = tasks.get(selected_task_id)
            if not task:
                raise _statem_error(f"Unknown TeamRun task: {selected_task_id}")
            if task.get("status") != "open":
                raise _statem_error(f"TeamRun task {selected_task_id} is {task.get('status')}, not open")

            lease_seconds = int(lease_seconds)
            if lease_seconds <= 0:
                raise _statem_error("lease_seconds must be positive")
            now = _now()
            expires_at_epoch = time.time() + lease_seconds
            lease = {
                "agent_id": agent_id,
                "role": self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "",
                "claimed_at": now,
                "expires_at": _format_epoch(expires_at_epoch),
                "expires_at_epoch": expires_at_epoch,
                "lease_seconds": lease_seconds,
            }
            task["status"] = "leased"
            task["lease"] = lease
            task["updated_at"] = now
            if manifest.get("phase") == "divided":
                manifest["phase"] = "exploring"
                manifest.setdefault("history", []).append(
                    {"ts": now, "event": "advance", "from": "divided", "to": "exploring", "reason": "first_claim"}
                )
            manifest.setdefault("history", []).append({"ts": now, "event": "claim", "task_id": selected_task_id, "lease": lease})
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)

            assignment = _read_json(Path(str(task["assignment_path"])))
            payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=False)
            payload["claimed_task"] = {
                "task_id": selected_task_id,
                "lease": lease,
                "assignment_path": task["assignment_path"],
                "assignment": assignment,
                "work_dir": str(_team_work_dir(self.state_dir, state, current, checked_entry_id, selected_task_id, agent_id)),
            }
            return payload

    def report(
        self,
        task_id: str,
        report_file: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id, require_entry=True)
        normalized_task_id = _clean_task_id(task_id)
        agent_id = self.runtime._ensure_agent_identity(state)
        source_path = Path(report_file).expanduser().resolve()
        payload = _load_team_file(source_path)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") not in {"divided", "exploring"}:
                raise _statem_error(f"Cannot report task progress while TeamRun phase is {manifest.get('phase')!r}")
            _refresh_team_leases(manifest)

            task = (manifest.get("tasks") or {}).get(normalized_task_id)
            if not task:
                raise _statem_error(f"Unknown TeamRun task: {normalized_task_id}")
            if task.get("status") != "leased":
                raise _statem_error(f"TeamRun task {normalized_task_id} must be leased before report; got {task.get('status')}")

            lease = task.get("lease") or {}
            if lease.get("agent_id") != agent_id:
                raise _statem_error(
                    f"TeamRun task {normalized_task_id} is leased by {lease.get('agent_id') or '(unknown)'}, not {agent_id}"
                )

            report = _normalize_team_report(payload, agent_id, self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "")
            report_dir = _team_task_dir(self.state_dir, state, current, checked_entry_id, normalized_task_id) / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            existing = sorted(report_dir.glob(f"{_clean_agent_id(agent_id)}-*.json"))
            report_index = len(existing) + 1
            report_path = report_dir / f"{_clean_agent_id(agent_id)}-{report_index:04d}.json"
            while report_path.exists():
                report_index += 1
                report_path = report_dir / f"{_clean_agent_id(agent_id)}-{report_index:04d}.json"

            now = _now()
            report_record = {
                "version": 1,
                "run_id": state["run_id"],
                "node": current,
                "entry_id": checked_entry_id,
                "task_id": normalized_task_id,
                "producer": report["producer"],
                "reported_at": now,
                "status": report["status"],
                "summary": report.get("summary"),
                "claims": report.get("claims", []),
                "evidence": report.get("evidence", []),
                "coverage": report.get("coverage", {}),
                "raw": report.get("raw", payload),
            }
            _write_json(report_path, report_record)

            task["report_count"] = int(task.get("report_count") or 0) + 1
            task["latest_report_path"] = str(report_path)
            task["latest_report_at"] = now
            task["updated_at"] = now
            manifest.setdefault("history", []).append(
                {
                    "ts": now,
                    "event": "report",
                    "task_id": normalized_task_id,
                    "agent_id": agent_id,
                    "status": report["status"],
                    "claims": len(report.get("claims") or []),
                }
            )
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)

            status_payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=True)
            status_payload["reported_task"] = {
                "task_id": normalized_task_id,
                "report_path": str(report_path),
                "status": report["status"],
                "claims": len(report.get("claims") or []),
            }
            return status_payload

    def submit(
        self,
        task_id: str,
        result_file: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id, require_entry=True)
        normalized_task_id = _clean_task_id(task_id)
        agent_id = self.runtime._ensure_agent_identity(state)
        source_path = Path(result_file).expanduser().resolve()
        payload = _load_team_file(source_path)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") not in {"divided", "exploring"}:
                raise _statem_error(f"Cannot submit task results while TeamRun phase is {manifest.get('phase')!r}")
            _refresh_team_leases(manifest)

            task = (manifest.get("tasks") or {}).get(normalized_task_id)
            if not task:
                raise _statem_error(f"Unknown TeamRun task: {normalized_task_id}")
            if task.get("status") != "leased":
                raise _statem_error(f"TeamRun task {normalized_task_id} must be leased before submit; got {task.get('status')}")

            lease = task.get("lease") or {}
            if lease.get("agent_id") != agent_id:
                raise _statem_error(
                    f"TeamRun task {normalized_task_id} is leased by {lease.get('agent_id') or '(unknown)'}, not {agent_id}"
                )

            config = manifest.get("config") or {}
            _validate_schema_payload(payload, config.get("result_schema"), f"TeamRun result {source_path}")
            result = _normalize_team_result(payload, agent_id, self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "")
            children = _normalize_team_child_assignments(
                result.get("children", []),
                parent_id=normalized_task_id,
                parent_depth=int(task.get("depth") or 0),
            )
            _ensure_new_team_task_ids(manifest, children)
            _validate_team_assignments(children, config.get("task_schema"))

            result_dir = _team_task_dir(self.state_dir, state, current, checked_entry_id, normalized_task_id) / "results"
            result_dir.mkdir(parents=True, exist_ok=True)
            result_path = result_dir / f"{agent_id}.json"
            if result_path.exists():
                raise _statem_error(f"TeamRun result already exists for task {normalized_task_id} and agent {agent_id}")

            now = _now()
            result_record = {
                "version": 1,
                "run_id": state["run_id"],
                "node": current,
                "entry_id": checked_entry_id,
                "task_id": normalized_task_id,
                "producer": result["producer"],
                "submitted_at": now,
                "status": result["status"],
                "summary": result.get("summary"),
                "claims": result.get("claims", []),
                "evidence": result.get("evidence", []),
                "coverage": result.get("coverage", {}),
                "children": result.get("children", []),
                "prune_proposals": result.get("prune_proposals", []),
                "raw": result.get("raw", payload),
            }
            _write_json(result_path, result_record)

            task["status"] = result["status"]
            task["lease"] = None
            task["last_lease"] = lease
            task["result_count"] = int(task.get("result_count") or 0) + 1
            task["result_path"] = str(result_path)
            task["updated_at"] = now

            for child in children:
                child_id = child["task_id"]
                assignment_path = _team_assignment_path(self.state_dir, state, current, checked_entry_id, child_id)
                assignment_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json(
                    assignment_path,
                    {
                        "version": 1,
                        "run_id": state["run_id"],
                        "node": current,
                        "entry_id": checked_entry_id,
                        "task_id": child_id,
                        "parent_id": normalized_task_id,
                        "depth": child.get("depth", int(task.get("depth") or 0) + 1),
                        "created_at": now,
                        "assignment": child["assignment"],
                    },
                )
                (manifest.setdefault("tasks", {}))[child_id] = _new_team_task_record(
                    child_id,
                    parent_id=normalized_task_id,
                    depth=int(child.get("depth") or 0),
                    priority=child.get("priority"),
                    assignment_path=str(assignment_path),
                    created_at=now,
                )

            manifest.setdefault("history", []).append(
                {
                    "ts": now,
                    "event": "submit",
                    "task_id": normalized_task_id,
                    "agent_id": agent_id,
                    "status": result["status"],
                    "children": len(children),
                }
            )
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)

            status_payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=True)
            status_payload["submitted_task"] = {
                "task_id": normalized_task_id,
                "result_path": str(result_path),
                "status": result["status"],
                "children": len(children),
            }
            return status_payload

    def release(
        self,
        task_id: str | None = None,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        all_leased: bool = False,
        agent_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id, require_entry=True)
        normalized_task_id = _clean_task_id(task_id) if task_id else None
        if not normalized_task_id and not all_leased:
            raise _statem_error("TeamRun release requires a task_id or --all-leased")
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") not in {"divided", "exploring"}:
                raise _statem_error(f"Cannot release leases while TeamRun phase is {manifest.get('phase')!r}")
            _refresh_team_leases(manifest)
            tasks = manifest.get("tasks") or {}
            released: list[dict[str, Any]] = []
            for candidate_id, task in tasks.items():
                if normalized_task_id and candidate_id != normalized_task_id:
                    continue
                if task.get("status") != "leased":
                    if normalized_task_id:
                        raise _statem_error(f"TeamRun task {candidate_id} is {task.get('status')}, not leased")
                    continue
                lease = task.get("lease") or {}
                if agent_id and lease.get("agent_id") != agent_id:
                    if normalized_task_id:
                        raise _statem_error(
                            f"TeamRun task {candidate_id} is leased by {lease.get('agent_id') or '(unknown)'}, not {agent_id}"
                        )
                    continue
                now = _now()
                task["status"] = "open"
                task["last_lease"] = lease
                task["lease"] = None
                task["updated_at"] = now
                released.append({"task_id": candidate_id, "agent_id": lease.get("agent_id"), "reason": reason})
            if normalized_task_id and not released:
                raise _statem_error(f"No matching leased TeamRun task to release: {normalized_task_id}")
            now = _now()
            manifest["updated_at"] = now
            manifest.setdefault("history", []).append(
                {
                    "ts": now,
                    "event": "release",
                    "tasks": released,
                    "reason": reason,
                    "agent_id_filter": agent_id,
                }
            )
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)
            payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=False)
            payload["released"] = released
            return payload

    def advance(
        self, phase: str, *, run_id: str | None = None, entry_id: str | None = None
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        target_phase = str(phase)
        if target_phase not in TEAM_PHASES:
            raise _statem_error(f"Unknown TeamRun phase: {target_phase}")
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            source_phase = str(manifest.get("phase") or "")
            if target_phase == source_phase:
                return self._status_payload(state, current, checked_entry_id, manifest, include_results=True)
            allowed = {
                "divided": {"exploring", "blocked"},
                "exploring": {"reducing", "blocked"},
                "reducing": {"exploring", "blocked"},
                "blocked": {"exploring"},
                "decided": set(),
            }
            if target_phase not in allowed.get(source_phase, set()):
                raise _statem_error(f"Cannot advance TeamRun from {source_phase!r} to {target_phase!r}")
            if target_phase == "reducing":
                _refresh_team_leases(manifest)
                blockers = [
                    task_id
                    for task_id, task in (manifest.get("tasks") or {}).items()
                    if task.get("status") not in TEAM_CLOSED_TASK_STATUSES
                ]
                if blockers:
                    raise _statem_error(
                        "Cannot advance TeamRun to reducing while tasks are still open or leased: "
                        + ", ".join(sorted(blockers))
                    )
            now = _now()
            manifest["phase"] = target_phase
            manifest["updated_at"] = now
            manifest.setdefault("history", []).append({"ts": now, "event": "advance", "from": source_phase, "to": target_phase})
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)
            return self._status_payload(state, current, checked_entry_id, manifest, include_results=True)

    def reduce_input(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            directory = team_dir(self.state_dir, state, current, checked_entry_id)
            payload = _team_reduce_input_payload(state, current, checked_entry_id, manifest, directory)
            if output_file:
                output_path = Path(output_file).expanduser()
                if not output_path.is_absolute():
                    output_path = (spec.path.parent / output_path).resolve()
            else:
                output_path = directory / "reduce" / "reducer-input.json"
            _write_json(output_path, payload)
            manifest["reducer_input_path"] = str(output_path)
            manifest.setdefault("history", []).append({"ts": _now(), "event": "reduce_input", "path": str(output_path)})
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)
            return {
                "run_id": state["run_id"],
                "current": current,
                "current_entry_id": checked_entry_id,
                "phase": manifest.get("phase"),
                "path": str(output_path),
                "reduce_input": payload,
            }

    def reduce(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") != "reducing":
                raise _statem_error(f"TeamRun must be in reducing phase before reduce; got {manifest.get('phase')!r}")
            directory = team_dir(self.state_dir, state, current, checked_entry_id)
            reduce_dir = directory / "reduce"
            reduce_dir.mkdir(parents=True, exist_ok=True)
            reducer_input_path = reduce_dir / "reducer-input.json"
            reducer_input = _team_reduce_input_payload(state, current, checked_entry_id, manifest, directory)
            _write_json(reducer_input_path, reducer_input)

            config = manifest.get("config") or {}
            reducer_config = dict(config.get("reducer") or {})
            if strategy:
                reducer_config["strategy"] = strategy
            decision_payload = _team_reduce_decision(reducer_input, reducer_config)
            decision_path = reduce_dir / "decision.json"
            _write_json(
                decision_path,
                {
                    "version": 1,
                    "run_id": state["run_id"],
                    "node": current,
                    "entry_id": checked_entry_id,
                    "producer": {
                        "agent_id": self.runtime._ensure_agent_identity(state),
                        "role": self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "reducer",
                    },
                    "decided_at": _now(),
                    "source_path": str(reducer_input_path),
                    "decision": decision_payload,
                },
            )
            now = _now()
            manifest["reducer_input_path"] = str(reducer_input_path)
            if decision_payload.get("status") == "blocked":
                manifest["phase"] = "blocked"
                manifest["blocked_decision_path"] = str(decision_path)
                manifest.setdefault("history", []).append({"ts": now, "event": "reduce_blocked", "decision_path": str(decision_path)})
            else:
                manifest["phase"] = "decided"
                manifest["decision_path"] = str(decision_path)
                manifest.setdefault("history", []).append({"ts": now, "event": "reduce_decide", "decision_path": str(decision_path)})
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)
            payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=True)
            payload["reducer_input_path"] = str(reducer_input_path)
            payload["decision_path"] = str(decision_path)
            payload["decision"] = decision_payload
            return payload

    def decide(
        self, decision_file: str, *, run_id: str | None = None, entry_id: str | None = None
    ) -> dict[str, Any]:
        _spec, state, current, checked_entry_id = self._load_current(run_id, entry_id)
        source_path = Path(decision_file).expanduser().resolve()
        decision_payload = _load_team_file(source_path)
        with _TeamManifestLock(_team_lock_path(self.state_dir, state, current, checked_entry_id)):
            manifest = self._load_manifest(state, current, checked_entry_id)
            if manifest.get("phase") != "reducing":
                raise _statem_error(f"TeamRun must be in reducing phase before decide; got {manifest.get('phase')!r}")
            reduce_dir = team_dir(self.state_dir, state, current, checked_entry_id) / "reduce"
            reduce_dir.mkdir(parents=True, exist_ok=True)
            decision_path = reduce_dir / "decision.json"
            if decision_path.exists():
                raise _statem_error(f"TeamRun decision already exists: {decision_path}")
            now = _now()
            _write_json(
                decision_path,
                {
                    "version": 1,
                    "run_id": state["run_id"],
                    "node": current,
                    "entry_id": checked_entry_id,
                    "producer": {
                        "agent_id": self.runtime._ensure_agent_identity(state),
                        "role": self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "",
                    },
                    "decided_at": now,
                    "source_path": str(source_path),
                    "decision": decision_payload,
                },
            )
            manifest["phase"] = "decided"
            manifest["decision_path"] = str(decision_path)
            manifest["updated_at"] = now
            manifest.setdefault("history", []).append({"ts": now, "event": "decide", "decision_path": str(decision_path)})
            _write_team_manifest(self.state_dir, state, current, checked_entry_id, manifest)
            self.runtime._write_state(state)
            payload = self._status_payload(state, current, checked_entry_id, manifest, include_results=True)
            payload["decision_path"] = str(decision_path)
            return payload

    def _load_current(
        self,
        run_id: str | None,
        entry_id: str | None,
        *,
        require_entry: bool = False,
    ) -> tuple[Any, dict[str, Any], str, str]:
        spec, state = self.runtime._load_runtime(run_id)
        current = str(state["current"])
        config = _normalize_team_config(spec.nodes[current].get(TEAM_PURPOSE))
        if not config:
            raise _statem_error(f"Current node '{current}' does not declare {TEAM_PURPOSE}")
        checked_entry_id = self._assert_entry(state, entry_id, required=require_entry)
        return spec, state, current, checked_entry_id

    def _assert_entry(self, state: dict[str, Any], entry_id: str | None, *, required: bool = False) -> str:
        current_entry_id = str(state.get("current_entry_id") or "")
        selected = str(entry_id or os.environ.get("STATEM_ENTRY_ID") or current_entry_id).strip()
        if required and not selected:
            raise _statem_error("TeamRun submit requires --entry-id or STATEM_ENTRY_ID so stale worker results cannot cross entries")
        if current_entry_id and selected and selected != current_entry_id:
            raise _statem_error(f"Stale TeamRun entry: got {selected}, but current entry is {current_entry_id}")
        return selected or current_entry_id

    def _load_manifest(self, state: dict[str, Any], node_name: str, entry_id: str) -> dict[str, Any]:
        manifest_path = _team_manifest_path(self.state_dir, state, node_name, entry_id)
        if not manifest_path.exists():
            raise _statem_error(f"TeamRun is not initialized for entry {entry_id}; run 'statem team init TASKS_FILE'")
        manifest = _read_json(manifest_path)
        if manifest.get("run_id") != state.get("run_id") or manifest.get("node") != node_name or manifest.get("entry_id") != entry_id:
            raise _statem_error(f"TeamRun manifest entry mismatch in {manifest_path}")
        return manifest

    def _status_payload(
        self,
        state: dict[str, Any],
        node_name: str,
        entry_id: str,
        manifest: dict[str, Any],
        *,
        include_results: bool,
    ) -> dict[str, Any]:
        directory = team_dir(self.state_dir, state, node_name, entry_id)
        payload: dict[str, Any] = {
            "run_id": state["run_id"],
            "current": node_name,
            "current_entry_id": entry_id,
            "path": str(directory),
            "phase": manifest.get("phase"),
            "counts": _team_counts(manifest),
            "frontier": _team_frontier_summary(manifest),
            "tasks": _team_task_summaries(manifest),
            "history_tail": (manifest.get("history") or [])[-20:],
        }
        if manifest.get("decision_path"):
            payload["decision_path"] = manifest["decision_path"]
        if include_results:
            payload["reports"] = _team_report_summaries(directory)
            payload["results"] = _team_result_summaries(directory)
        return payload


class _TeamManifestLock:
    def __init__(self, path: Path, *, timeout_seconds: float = 30.0, stale_after_seconds: float = 600.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.stale_after_seconds = stale_after_seconds

    def __enter__(self) -> "_TeamManifestLock":
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                self.path.mkdir(parents=True)
                (self.path / "owner.json").write_text(
                    json.dumps({"pid": os.getpid(), "created_at": _now()}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return self
            except FileExistsError:
                self._break_stale_lock()
                if time.time() >= deadline:
                    raise _statem_error(f"Timed out waiting for TeamRun lock: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def _break_stale_lock(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age > self.stale_after_seconds:
            shutil.rmtree(self.path, ignore_errors=True)


def _normalize_team_config(raw_config: Any) -> dict[str, Any]:
    if raw_config is None or raw_config == "":
        return {}
    if not isinstance(raw_config, dict):
        raise _statem_error(f"{TEAM_PURPOSE} must be a mapping")
    config = dict(raw_config)
    config["mode"] = str(config.get("mode") or "fanout_search_reduce")
    config["max_parallel"] = int(config.get("max_parallel") or 0)
    config["required"] = bool(config.get("required", True))
    config["require_all_tasks_done"] = bool(config.get("require_all_tasks_done", True))
    reducer = config.get("reducer")
    if reducer is None:
        config["reducer"] = {}
    elif isinstance(reducer, str):
        config["reducer"] = {"strategy": reducer}
    elif isinstance(reducer, dict):
        config["reducer"] = dict(reducer)
    else:
        raise _statem_error(f"{TEAM_PURPOSE} reducer must be a mapping or string")
    return config


def _normalize_team_schema(raw_schema: Any) -> dict[str, Any]:
    if raw_schema is None or raw_schema == "":
        return {}
    if isinstance(raw_schema, str):
        if raw_schema not in TEAM_BUILTIN_SCHEMAS:
            raise _statem_error(f"unknown schema {raw_schema!r}")
        schema = dict(TEAM_BUILTIN_SCHEMAS[raw_schema])
        schema["name"] = raw_schema
        return schema
    if not isinstance(raw_schema, dict):
        raise _statem_error("schema must be a string or mapping")
    schema = dict(raw_schema)
    required = schema.get("required", [])
    if required is None:
        required = []
    if not isinstance(required, list):
        raise _statem_error("required must be a list")
    schema["required"] = [str(item) for item in required]
    types = schema.get("types", {})
    if types is None:
        types = {}
    if not isinstance(types, dict):
        raise _statem_error("types must be a mapping")
    schema["types"] = {str(key): str(value) for key, value in types.items()}
    return schema


def _validate_schema_payload(payload: Any, raw_schema: Any, label: str) -> None:
    schema = _normalize_team_schema(raw_schema)
    if not schema:
        return
    problems: list[str] = []
    for path in schema.get("required", []):
        found, value = _json_path(payload, str(path))
        if not found or value in (None, ""):
            problems.append(f"{label}: required field missing: {path}")
    for path, expected_type in schema.get("types", {}).items():
        found, value = _json_path(payload, str(path))
        if not found:
            continue
        if not _schema_type_matches(value, expected_type):
            problems.append(f"{label}: field {path} expected {expected_type}, got {type(value).__name__}")
    if problems:
        raise _statem_error("; ".join(problems))


def _validate_team_assignments(assignments: list[dict[str, Any]], raw_schema: Any) -> None:
    for assignment in assignments:
        _validate_schema_payload(assignment["assignment"], raw_schema, f"TeamRun task {assignment['task_id']}")


def _schema_type_matches(value: Any, expected_type: str) -> bool:
    normalized = expected_type.lower()
    if normalized in {"string", "str"}:
        return isinstance(value, str)
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"number", "float"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"list", "array"}:
        return isinstance(value, list)
    if normalized in {"mapping", "object", "dict"}:
        return isinstance(value, dict)
    if normalized == "any":
        return True
    raise _statem_error(f"unsupported schema type {expected_type!r}")


def _load_team_file(path: Path) -> Any:
    if not path.exists():
        raise _statem_error(f"TeamRun file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text) if path.suffix.lower() == ".json" else miniyaml.loads(text)
    except Exception as exc:
        raise _statem_error(f"Could not parse TeamRun file {path}: {exc}") from exc


def _team_payload_tasks(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        return payload["tasks"]
    raise _statem_error("TeamRun tasks must be a list or a mapping with a tasks list")


def _normalize_team_assignments(payload: Any) -> list[dict[str, Any]]:
    return _normalize_team_assignment_list(_team_payload_tasks(payload), parent_id=None, parent_depth=-1)


def _normalize_team_child_assignments(children: Any, *, parent_id: str, parent_depth: int) -> list[dict[str, Any]]:
    if children is None:
        return []
    if not isinstance(children, list):
        raise _statem_error("TeamRun result children must be a list")
    return _normalize_team_assignment_list(children, parent_id=parent_id, parent_depth=parent_depth)


def _normalize_team_assignment_list(
    raw_tasks: list[Any], *, parent_id: str | None, parent_depth: int
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_task in enumerate(raw_tasks, start=1):
        if not isinstance(raw_task, dict):
            raise _statem_error(f"TeamRun task {index} must be a mapping")
        raw_id = raw_task.get("task_id") or raw_task.get("id")
        if raw_id is None:
            raise _statem_error(f"TeamRun task {index} requires task_id or id")
        task_id = _clean_task_id(str(raw_id))
        if task_id in seen:
            raise _statem_error(f"Duplicate TeamRun task id: {task_id}")
        seen.add(task_id)
        assignment = dict(raw_task)
        assignment["task_id"] = task_id
        if str(raw_id) != task_id:
            assignment["raw_task_id"] = str(raw_id)
        normalized_parent = parent_id
        if normalized_parent is None and raw_task.get("parent_id") is not None:
            normalized_parent = _clean_task_id(str(raw_task["parent_id"]))
        if normalized_parent is not None:
            assignment["parent_id"] = normalized_parent
        depth = int(raw_task.get("depth") if raw_task.get("depth") is not None else parent_depth + 1)
        assignments.append(
            {
                "task_id": task_id,
                "parent_id": normalized_parent,
                "depth": depth,
                "priority": raw_task.get("priority", 0),
                "assignment": assignment,
            }
        )
    return assignments


def _ensure_new_team_task_ids(manifest: dict[str, Any], assignments: list[dict[str, Any]]) -> None:
    existing = set((manifest.get("tasks") or {}).keys())
    seen: set[str] = set()
    duplicates: list[str] = []
    for assignment in assignments:
        task_id = assignment["task_id"]
        if task_id in existing or task_id in seen:
            duplicates.append(task_id)
        seen.add(task_id)
    if duplicates:
        raise _statem_error("TeamRun child task id already exists: " + ", ".join(sorted(set(duplicates))))


def _new_team_task_record(
    task_id: str,
    *,
    parent_id: str | None,
    depth: int,
    priority: Any,
    assignment_path: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "parent_id": parent_id,
        "depth": depth,
        "priority": priority if priority is not None else 0,
        "status": "open",
        "assignment_path": assignment_path,
        "created_at": created_at,
        "updated_at": created_at,
        "lease": None,
        "result_count": 0,
    }


def _normalize_team_result(payload: Any, agent_id: str, role: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _statem_error("TeamRun result must be a mapping")
    status = str(payload.get("status") or "completed")
    allowed = {"completed", "terminal", "expanded", "exhausted", "failed", "blocked", "partial"}
    if status not in allowed:
        raise _statem_error(f"TeamRun result status must be one of {', '.join(sorted(allowed))}; got {status!r}")
    for key in ("claims", "evidence", "children", "prune_proposals"):
        if key in payload and not isinstance(payload[key], list):
            raise _statem_error(f"TeamRun result {key} must be a list")
    if "coverage" in payload and not isinstance(payload["coverage"], dict):
        raise _statem_error("TeamRun result coverage must be a mapping")
    if not agent_id:
        raise _statem_error("TeamRun result requires an agent id")
    producer = payload.get("producer") if isinstance(payload.get("producer"), dict) else {}
    return {
        "producer": {
            "agent_id": _clean_agent_id(str(agent_id or producer.get("agent_id") or "")),
            "role": str(role or producer.get("role") or ""),
        },
        "status": status,
        "summary": payload.get("summary", payload.get("answer")),
        "claims": payload.get("claims", []),
        "evidence": payload.get("evidence", []),
        "coverage": payload.get("coverage", {}),
        "children": payload.get("children", []),
        "prune_proposals": payload.get("prune_proposals", []),
        "raw": payload,
    }


def _normalize_team_report(payload: Any, agent_id: str, role: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _statem_error("TeamRun report must be a mapping")
    status = str(payload.get("status") or "partial")
    allowed = {"completed", "terminal", "expanded", "exhausted", "failed", "blocked", "partial", "progress"}
    if status not in allowed:
        raise _statem_error(f"TeamRun report status must be one of {', '.join(sorted(allowed))}; got {status!r}")
    for key in ("claims", "evidence"):
        if key in payload and not isinstance(payload[key], list):
            raise _statem_error(f"TeamRun report {key} must be a list")
    if "coverage" in payload and not isinstance(payload["coverage"], dict):
        raise _statem_error("TeamRun report coverage must be a mapping")
    if not agent_id:
        raise _statem_error("TeamRun report requires an agent id")
    producer = payload.get("producer") if isinstance(payload.get("producer"), dict) else {}
    return {
        "producer": {
            "agent_id": _clean_agent_id(str(agent_id or producer.get("agent_id") or "")),
            "role": str(role or producer.get("role") or ""),
        },
        "status": status,
        "summary": payload.get("summary", payload.get("answer")),
        "claims": payload.get("claims", []),
        "evidence": payload.get("evidence", []),
        "coverage": payload.get("coverage", {}),
        "raw": payload,
    }


def _refresh_team_leases(manifest: dict[str, Any]) -> bool:
    changed = False
    now_epoch = time.time()
    for task in (manifest.get("tasks") or {}).values():
        if task.get("status") != "leased":
            continue
        lease = task.get("lease") or {}
        expires_at_epoch = float(lease.get("expires_at_epoch") or 0)
        if expires_at_epoch and expires_at_epoch <= now_epoch:
            task["status"] = "open"
            task["expired_lease"] = lease
            task["lease"] = None
            task["updated_at"] = _now()
            manifest.setdefault("history", []).append(
                {"ts": _now(), "event": "lease_expired", "task_id": task.get("task_id"), "lease": lease}
            )
            changed = True
    return changed


def _normalize_claim_shard(worker_index: int | None, worker_count: int | None) -> tuple[int, int] | None:
    if worker_index is None and worker_count is None:
        return None
    if worker_index is None or worker_count is None:
        raise _statem_error("TeamRun sharded claim requires both worker_index and worker_count")
    index = int(worker_index)
    count = int(worker_count)
    if count <= 0:
        raise _statem_error("worker_count must be positive")
    if index < 0 or index >= count:
        raise _statem_error(f"worker_index must be in [0, {count - 1}], got {index}")
    return index, count


def _select_open_team_task(manifest: dict[str, Any], *, shard: tuple[int, int] | None = None) -> str | None:
    ordered_tasks = sorted((manifest.get("tasks") or {}).values(), key=_team_task_order_key)
    open_tasks = [task for task in ordered_tasks if task.get("status") == "open"]
    if not open_tasks:
        return None
    if shard is not None:
        worker_index, worker_count = shard
        shard_tasks = [
            task
            for position, task in enumerate(ordered_tasks)
            if task.get("status") == "open" and position % worker_count == worker_index
        ]
        if shard_tasks:
            return str(shard_tasks[0]["task_id"])
    return str(open_tasks[0]["task_id"])


def _team_task_order_key(task: dict[str, Any]) -> tuple[float, int, str, str]:
    return (
        -float(task.get("priority") or 0),
        int(task.get("depth") or 0),
        str(task.get("created_at") or ""),
        str(task.get("task_id") or ""),
    )


def _team_frontier_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    tasks = manifest.get("tasks") or {}
    open_tasks = [task for task in tasks.values() if task.get("status") == "open"]
    leased_tasks = [task for task in tasks.values() if task.get("status") == "leased"]
    terminal_tasks = [task for task in tasks.values() if task.get("status") in {"terminal", "completed"}]
    open_tasks.sort(key=_team_task_order_key)
    leased_tasks.sort(key=lambda task: str((task.get("lease") or {}).get("expires_at") or ""))
    recommended: list[str] = []
    if open_tasks:
        recommended.append("claim_or_dispatch_open_tasks")
    if leased_tasks:
        recommended.append("wait_for_or_release_leases")
    if not open_tasks and not leased_tasks and manifest.get("phase") == "exploring":
        recommended.append("advance_to_reducing")
    if manifest.get("phase") == "reducing":
        recommended.append("write_reduce_input_and_decision")
    return {
        "open": [
            {
                "task_id": task.get("task_id"),
                "parent_id": task.get("parent_id"),
                "depth": task.get("depth"),
                "priority": task.get("priority"),
                "assignment_path": task.get("assignment_path"),
            }
            for task in open_tasks[:20]
        ],
        "leased": [
            {
                "task_id": task.get("task_id"),
                "lease": task.get("lease"),
                "assignment_path": task.get("assignment_path"),
            }
            for task in leased_tasks
        ],
        "terminal_candidates": [
            {
                "task_id": task.get("task_id"),
                "status": task.get("status"),
                "result_path": task.get("result_path"),
            }
            for task in terminal_tasks[:20]
        ],
        "recommended_actions": recommended,
    }


def _team_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts = {status: 0 for status in ["open", "leased", "completed", "terminal", "expanded", "exhausted", "failed", "blocked", "partial", "pruned"]}
    for task in (manifest.get("tasks") or {}).values():
        status = str(task.get("status") or "open")
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = sum(count for key, count in counts.items() if key != "total")
    counts["closed"] = sum(counts.get(status, 0) for status in TEAM_CLOSED_TASK_STATUSES)
    return counts


def _team_task_summaries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for task in (manifest.get("tasks") or {}).values():
        summary = {
            "task_id": task.get("task_id"),
            "parent_id": task.get("parent_id"),
            "depth": task.get("depth"),
            "priority": task.get("priority"),
            "status": task.get("status"),
            "assignment_path": task.get("assignment_path"),
            "result_count": task.get("result_count", 0),
            "result_path": task.get("result_path"),
            "report_count": task.get("report_count", 0),
            "latest_report_path": task.get("latest_report_path"),
        }
        if task.get("latest_report_at"):
            summary["latest_report_at"] = task["latest_report_at"]
        if task.get("lease"):
            summary["lease"] = task["lease"]
        summaries.append(summary)
    summaries.sort(key=lambda task: (int(task.get("depth") or 0), str(task.get("task_id") or "")))
    return summaries


def _team_full_results(task_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results_dir = task_dir / "results"
    if not results_dir.exists():
        return results
    for path in sorted(results_dir.glob("*.json")):
        try:
            result = _read_json(path)
        except Exception as exc:
            results.append({"path": str(path), "error": str(exc)})
            continue
        result["path"] = str(path)
        results.append(result)
    return results


def _team_full_reports(task_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    reports_dir = task_dir / "reports"
    if not reports_dir.exists():
        return reports
    for path in sorted(reports_dir.glob("*.json")):
        try:
            report = _read_json(path)
        except Exception as exc:
            reports.append({"path": str(path), "error": str(exc)})
            continue
        report["path"] = str(path)
        reports.append(report)
    return reports


def _team_result_summaries(directory: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    tasks_dir = directory / "tasks"
    if not tasks_dir.exists():
        return results
    for path in sorted(tasks_dir.glob("*/results/*.json")):
        try:
            result = _read_json(path)
        except Exception as exc:
            results.append({"path": str(path), "error": str(exc)})
            continue
        producer = result.get("producer") if isinstance(result.get("producer"), dict) else {}
        results.append(
            {
                "task_id": result.get("task_id"),
                "agent_id": producer.get("agent_id"),
                "role": producer.get("role"),
                "status": result.get("status"),
                "summary": result.get("summary"),
                "claims": len(result.get("claims") or []),
                "evidence": len(result.get("evidence") or []),
                "coverage": result.get("coverage", {}),
                "children": len(result.get("children") or []),
                "path": str(path),
            }
        )
    return results


def _team_report_summaries(directory: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    tasks_dir = directory / "tasks"
    if not tasks_dir.exists():
        return reports
    for path in sorted(tasks_dir.glob("*/reports/*.json")):
        try:
            report = _read_json(path)
        except Exception as exc:
            reports.append({"path": str(path), "error": str(exc)})
            continue
        producer = report.get("producer") if isinstance(report.get("producer"), dict) else {}
        reports.append(
            {
                "task_id": report.get("task_id"),
                "agent_id": producer.get("agent_id"),
                "role": producer.get("role"),
                "status": report.get("status"),
                "summary": report.get("summary"),
                "claims": len(report.get("claims") or []),
                "evidence": len(report.get("evidence") or []),
                "coverage": report.get("coverage", {}),
                "reported_at": report.get("reported_at"),
                "path": str(path),
            }
        )
    return reports


def _team_reduce_input_payload(
    state: dict[str, Any], node_name: str, entry_id: str, manifest: dict[str, Any], directory: Path
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for task in _team_task_summaries(manifest):
        assignment_path = Path(str(task.get("assignment_path") or ""))
        assignment = _read_json(assignment_path) if assignment_path.exists() else {}
        task_directory = directory / "tasks" / _clean_task_id(str(task.get("task_id") or ""))
        tasks.append(
            {
                "task": task,
                "assignment": assignment,
                "reports": _team_full_reports(task_directory),
                "results": _team_full_results(task_directory),
            }
        )
    return {
        "version": 1,
        "run_id": state["run_id"],
        "node": node_name,
        "entry_id": entry_id,
        "phase": manifest.get("phase"),
        "counts": _team_counts(manifest),
        "frontier": _team_frontier_summary(manifest),
        "tasks": tasks,
        "prune_proposals": manifest.get("prune_proposals", []),
        "generated_at": _now(),
    }


def _team_reduce_decision(payload: dict[str, Any], reducer_config: dict[str, Any]) -> dict[str, Any]:
    strategy = str(reducer_config.get("strategy") or "all-claims-table")
    candidate_field = str(reducer_config.get("candidate_field") or "candidate_frame")
    confidence_field = str(reducer_config.get("confidence_field") or "confidence")
    require_complete_coverage = bool(reducer_config.get("require_complete_coverage", False))
    claims = _team_reduce_claims(payload)
    coverage = _team_reduce_coverage(payload)
    if require_complete_coverage or strategy == "coverage-required":
        coverage_decision = _team_coverage_decision(payload, claims, coverage)
        if strategy == "coverage-required" or coverage_decision["status"] == "blocked":
            return coverage_decision
    if strategy == "earliest-candidate":
        return _team_candidate_decision(payload, claims, coverage, candidate_field, confidence_field, earliest=True)
    if strategy == "highest-confidence":
        return _team_candidate_decision(payload, claims, coverage, candidate_field, confidence_field, earliest=False)
    if strategy == "all-claims-table":
        status = "decided" if claims else "blocked"
        return {
            "strategy": strategy,
            "status": status,
            "answer": f"{len(claims)} claim(s) collected",
            "coverage": coverage,
            "claims": claims,
            "evidence_refs": _team_evidence_refs(claims),
            "source": _team_reduce_source(payload),
        }
    raise _statem_error(f"Unsupported TeamRun reducer strategy: {strategy}")


def _team_reduce_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for task_entry in payload.get("tasks", []):
        task = task_entry.get("task") or {}
        task_id = str(task.get("task_id") or "")
        entries: list[tuple[str, dict[str, Any]]] = []
        entries.extend(("report", report) for report in task_entry.get("reports", []))
        entries.extend(("result", result) for result in task_entry.get("results", []))
        for source_kind, result in entries:
            producer = result.get("producer") if isinstance(result.get("producer"), dict) else {}
            result_path = str(result.get("path") or (task.get("result_path") if source_kind == "result" else "") or "")
            for index, raw_claim in enumerate(result.get("claims") or []):
                claim = dict(raw_claim) if isinstance(raw_claim, dict) else {"claim": raw_claim}
                claim["_task_id"] = task_id
                claim["_claim_index"] = index
                claim["_result_path"] = result_path
                claim["_agent_id"] = producer.get("agent_id")
                claim["_result_status"] = result.get("status")
                claim["_source"] = source_kind
                claims.append(claim)
    return claims


def _team_reduce_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    total = 0
    complete_or_pruned = 0
    incomplete_tasks: list[str] = []
    open_tasks: list[str] = []
    failed_tasks: list[str] = []
    for task_entry in payload.get("tasks", []):
        total += 1
        task = task_entry.get("task") or {}
        task_id = str(task.get("task_id") or "")
        status = str(task.get("status") or "")
        if status in {"open", "leased"}:
            open_tasks.append(task_id)
        if status in {"failed", "blocked", "partial"}:
            failed_tasks.append(task_id)
        coverages = [
            result.get("coverage")
            for result in task_entry.get("results", [])
            if isinstance(result.get("coverage"), dict)
        ]
        task_complete = bool(coverages) and all(bool(coverage.get("complete")) for coverage in coverages)
        if task_complete or status == "pruned":
            complete_or_pruned += 1
        else:
            incomplete_tasks.append(task_id)
    return {
        "total_tasks": total,
        "complete_or_pruned_tasks": complete_or_pruned,
        "incomplete_tasks": incomplete_tasks,
        "open_tasks": open_tasks,
        "failed_tasks": failed_tasks,
        "complete": not incomplete_tasks and not open_tasks and not failed_tasks,
    }


def _team_coverage_decision(
    payload: dict[str, Any], claims: list[dict[str, Any]], coverage: dict[str, Any]
) -> dict[str, Any]:
    status = "decided" if coverage["complete"] else "blocked"
    return {
        "strategy": "coverage-required",
        "status": status,
        "answer": "coverage complete" if status == "decided" else "coverage gaps remain",
        "coverage": coverage,
        "claims_count": len(claims),
        "evidence_refs": _team_evidence_refs(claims),
        "source": _team_reduce_source(payload),
    }


def _team_candidate_decision(
    payload: dict[str, Any],
    claims: list[dict[str, Any]],
    coverage: dict[str, Any],
    candidate_field: str,
    confidence_field: str,
    *,
    earliest: bool,
) -> dict[str, Any]:
    candidates = [claim for claim in claims if _number(claim.get(candidate_field)) is not None]
    strategy = "earliest-candidate" if earliest else "highest-confidence"
    if not candidates:
        return {
            "strategy": strategy,
            "status": "blocked",
            "answer": f"no claims contained {candidate_field}",
            "coverage": coverage,
            "candidates": [],
            "source": _team_reduce_source(payload),
        }
    if earliest:
        selected = min(
            candidates,
            key=lambda claim: (
                _number(claim.get(candidate_field)) or 0,
                -(_number(claim.get(confidence_field)) or 0),
            ),
        )
    else:
        selected = max(
            candidates,
            key=lambda claim: (
                _number(claim.get(confidence_field)) or 0,
                -(_number(claim.get(candidate_field)) or 0),
            ),
        )
    return {
        "strategy": strategy,
        "status": "decided",
        "answer": {
            candidate_field: selected.get(candidate_field),
            confidence_field: selected.get(confidence_field),
            "task_id": selected.get("_task_id"),
            "claim": selected.get("claim") or selected.get("text") or selected,
        },
        "selected_claim": selected,
        "candidate_field": candidate_field,
        "confidence_field": confidence_field,
        "coverage": coverage,
        "candidates": _team_candidate_rows(candidates, candidate_field, confidence_field),
        "evidence_refs": _team_evidence_refs([selected]),
        "source": _team_reduce_source(payload),
    }


def _team_candidate_rows(
    claims: list[dict[str, Any]], candidate_field: str, confidence_field: str
) -> list[dict[str, Any]]:
    return [
        {
            "task_id": claim.get("_task_id"),
            "agent_id": claim.get("_agent_id"),
            candidate_field: claim.get(candidate_field),
            confidence_field: claim.get(confidence_field),
            "claim": claim.get("claim") or claim.get("text"),
            "evidence_refs": claim.get("evidence_refs", []),
            "result_path": claim.get("_result_path"),
            "source": claim.get("_source"),
        }
        for claim in claims
    ]


def _team_evidence_refs(claims: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for claim in claims:
        for ref in claim.get("evidence_refs") or []:
            if str(ref) not in refs:
                refs.append(str(ref))
        result_path = claim.get("_result_path")
        if result_path and str(result_path) not in refs:
            refs.append(str(result_path))
    return refs


def _team_reduce_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload.get("run_id"),
        "node": payload.get("node"),
        "entry_id": payload.get("entry_id"),
        "generated_at": payload.get("generated_at"),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _team_manifest_path(state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str) -> Path:
    return team_dir(state_dir, state, node_name, entry_id) / "manifest.json"


def _team_lock_path(state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str) -> Path:
    return team_dir(state_dir, state, node_name, entry_id) / "manifest.lock"


def _team_task_dir(state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str, task_id: str) -> Path:
    return team_dir(state_dir, state, node_name, entry_id) / "tasks" / _clean_task_id(task_id)


def _team_assignment_path(state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str, task_id: str) -> Path:
    return _team_task_dir(state_dir, state, node_name, entry_id, task_id) / "assignment.json"


def _team_work_dir(
    state_dir: Path,
    state: dict[str, Any],
    node_name: str,
    entry_id: str,
    task_id: str,
    agent_id: str,
) -> Path:
    return _team_task_dir(state_dir, state, node_name, entry_id, task_id) / "work" / _clean_agent_id(agent_id)


def _write_team_manifest(
    state_dir: Path, state: dict[str, Any], node_name: str, entry_id: str, manifest: dict[str, Any]
) -> None:
    manifest["updated_at"] = _now()
    _write_json(_team_manifest_path(state_dir, state, node_name, entry_id), manifest)


def _team_gate_result(passed: bool, *, output: str) -> dict[str, Any]:
    return {
        "type": "manual",
        "purpose": TEAM_PURPOSE,
        "passed": passed,
        "blocking": True,
        "on_failure": "block",
        "continued": False,
        "output": output,
    }


def _json_path(data: Any, path: str) -> tuple[bool, Any]:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                return False, None
        return False, None
    return True, current


def _append_event(state: dict[str, Any], event: str, fields: dict[str, Any]) -> None:
    state.setdefault("history", []).append({"ts": _now(), "event": event, **fields})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _format_epoch(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _clean_run_id(run_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(run_id).strip())
    if not cleaned:
        raise _statem_error("run id cannot be empty")
    return cleaned


def _clean_agent_id(agent_id: str) -> str:
    if not agent_id:
        return ""
    raw = str(agent_id).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)
    return cleaned or "agent"


def _clean_task_id(task_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(task_id).strip())
    if not cleaned:
        raise _statem_error("task id cannot be empty")
    return cleaned


def _clean_node_id(node_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(node_name).strip())
    return cleaned or "node"
