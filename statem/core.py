from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import miniyaml


class StatemError(Exception):
    exit_code = 1

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class TransitionBlocked(StatemError):
    exit_code = 2


DYNAMIC_PURPOSE = "dynamic_before_transfer"
TEAM_PURPOSE = "multi_agent"
STATE_HOOKS_KEY = "state_hooks"
STATE_HOOK_PURPOSE = "state_hook"
GATING_PURPOSES = {"condition", "before_transfer", DYNAMIC_PURPOSE}
HOOK_KEYS = {"in_hook", "before_transfer", "out_hook", "condition", "hook"}
CHECK_TYPES = {"message", "manual", "checklist", "command", "predicate", "llm_review"}
DYNAMIC_CHECKS_SCHEMA_HINT = (
    "Accepted dynamic checks file shape: "
    "{'basis': {'implementation_summary': 'what changed and why these checks fit'}, "
    "'checks': ["
    "{'type': 'manual', 'prompt': 'Confirm ...', 'reason': '...'}, "
    "{'type': 'checklist', 'items': ['...'], 'reason': '...'}, "
    "{'type': 'predicate', 'path': '/app/file', 'exists': true, 'reason': '...'}, "
    "{'type': 'command', 'run': '...', 'reason': '...'}"
    "]}. Pass --agent-id or set STATEM_AGENT_ID; producer metadata is owned by the CLI."
)
STATE_HOOK_TEMPLATES = {"statem_autoloop"}
DEFAULT_STOP_STATES = {"handoff", "done", "complete", "completed", "finished"}

STRICT_ROOT_KEYS = {"name", "initial", "start", "nodes", "edges"}
STRICT_NODE_KEYS = {
    "name",
    "prompt",
    "pre_request",
    "pre-request",
    "next",
    "next_states",
    "in_hook",
    "before_transfer",
    DYNAMIC_PURPOSE,
    TEAM_PURPOSE,
    "out_hook",
    STATE_HOOKS_KEY,
}
STRICT_EDGE_KEYS = {
    "from",
    "source",
    "node1",
    "to",
    "target",
    "node2",
    "condition",
    "hook",
    "max_attempts",
}
STRICT_NESTED_EDGE_KEYS = {"to", "target", "name", "condition", "hook", "max_attempts"}
STRICT_DYNAMIC_CONFIG_KEYS = {
    "path",
    "required",
    "min_items",
    "require_reason",
    "require_basis",
    "merge",
    "refresh",
    "stale_policy",
    "allow_types",
}
STRICT_STATE_HOOK_KEYS = {
    "name",
    "event",
    "trigger",
    "on",
    "template",
    "type",
    "scope",
    "hosts",
    "host",
    "prompt",
    "text",
    "stop_states",
    "terminal_states",
}
STRICT_TEAM_CONFIG_KEYS = {
    "mode",
    "max_parallel",
    "required",
    "require_all_tasks_done",
    "reducer",
    "task_schema",
    "result_schema",
}
STRICT_TEAM_REDUCER_KEYS = {
    "strategy",
    "candidate_field",
    "confidence_field",
    "require_complete_coverage",
}
STRICT_TEAM_SCHEMA_KEYS = {"required", "types"}
STRICT_CHECK_COMMON_KEYS = {"type", "blocking", "on_failure"}
STRICT_CHECK_KEYS = {
    "message": STRICT_CHECK_COMMON_KEYS | {"text", "prompt"},
    "manual": STRICT_CHECK_COMMON_KEYS | {"prompt", "text", "name", "confirmation", "confirm"},
    "checklist": STRICT_CHECK_COMMON_KEYS | {"items", "checks", "confirmation", "confirm"},
    "command": STRICT_CHECK_COMMON_KEYS | {"run", "cmd", "command", "timeout", "cwd"},
    "predicate": STRICT_CHECK_COMMON_KEYS
    | {
        "path",
        "cwd",
        "exists",
        "non_empty",
        "contains",
        "not_contains",
        "matches",
        "json_path",
        "equals",
        "one_of",
    },
    "llm_review": STRICT_CHECK_COMMON_KEYS
    | {
        "run",
        "cmd",
        "command",
        "prompt",
        "text",
        "name",
        "timeout",
        "cwd",
        "stdin",
        "accept_contains",
        "reject_contains",
        "accept_regex",
        "reject_regex",
    },
}


@dataclass
class RunOptions:
    state_dir: Path
    yes: bool = False
    json_mode: bool = False
    run_id: str | None = None
    agent_id: str | None = None
    agent_role: str | None = None

    def emit(self, message: str) -> None:
        if message and not self.json_mode:
            print(message)


@dataclass
class StatemSpec:
    path: Path
    raw: dict[str, Any]
    name: str
    initial: str
    nodes: dict[str, dict[str, Any]]
    edges: list[dict[str, Any]]
    outgoing: dict[str, list[dict[str, Any]]]
    spec_hash: str

    @classmethod
    def load(cls, path: str | os.PathLike[str], *, strict: bool = False) -> "StatemSpec":
        spec_path = Path(path).expanduser().resolve()
        if not spec_path.exists():
            raise StatemError(f"Spec file not found: {spec_path}")
        text = spec_path.read_text(encoding="utf-8")
        raw = _load_mapping(text, spec_path)
        if strict:
            strict_errors = _strict_keyword_errors(raw)
            if strict_errors:
                raise StatemError(
                    "Invalid spec:\n" + "\n".join(f"- {error}" for error in strict_errors)
                )
        name = str(raw.get("name") or spec_path.stem)
        nodes = _normalize_nodes(raw.get("nodes"))
        if not nodes:
            raise StatemError("Spec must define at least one node")
        initial = str(raw.get("initial") or raw.get("start") or next(iter(nodes)))
        edges = _normalize_edges(raw, nodes)
        outgoing: dict[str, list[dict[str, Any]]] = {name: [] for name in nodes}
        for edge in edges:
            outgoing.setdefault(edge["from"], []).append(edge)
        spec = cls(
            path=spec_path,
            raw=raw,
            name=name,
            initial=initial,
            nodes=nodes,
            edges=edges,
            outgoing=outgoing,
            spec_hash=_sha256_text(text),
        )
        errors = spec.validation_errors()
        if errors:
            raise StatemError("Invalid spec:\n" + "\n".join(f"- {error}" for error in errors))
        return spec

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.initial not in self.nodes:
            errors.append(f"initial node '{self.initial}' is not defined")

        seen_edges: set[tuple[str, str]] = set()
        for index, edge in enumerate(self.edges, start=1):
            source = edge.get("from")
            target = edge.get("to")
            if source not in self.nodes:
                errors.append(f"edge {index} source '{source}' is not a node")
            if target not in self.nodes:
                errors.append(f"edge {index} target '{target}' is not a node")
            edge_key = (str(source), str(target))
            if edge_key in seen_edges:
                errors.append(f"duplicate edge '{source}' -> '{target}' makes goto ambiguous")
            seen_edges.add(edge_key)
            errors.extend(_validate_edge_max_attempts(edge, f"edge {source}->{target}"))
            errors.extend(_validate_items(edge.get("condition"), "condition", f"edge {source}->{target} condition"))
            errors.extend(_validate_items(edge.get("hook"), "hook", f"edge {source}->{target} hook"))

        for name, node in self.nodes.items():
            errors.extend(_validate_items(node.get("in_hook"), "in_hook", f"node {name} in_hook"))
            errors.extend(_validate_items(node.get("before_transfer"), "before_transfer", f"node {name} before_transfer"))
            errors.extend(_validate_items(node.get("out_hook"), "out_hook", f"node {name} out_hook"))
            errors.extend(_validate_dynamic_config(node.get(DYNAMIC_PURPOSE), f"node {name} {DYNAMIC_PURPOSE}"))
            from .team import validate_team_config

            errors.extend(validate_team_config(node.get(TEAM_PURPOSE), f"node {name} {TEAM_PURPOSE}"))
            errors.extend(_validate_state_hooks(node.get(STATE_HOOKS_KEY), f"node {name} {STATE_HOOKS_KEY}"))
        return errors

    def node_prompt(self, name: str) -> str:
        node = self.nodes[name]
        return str(node.get("prompt") or node.get("pre_request") or node.get("pre-request") or "")

    def edge_to(self, source: str, target: str) -> dict[str, Any] | None:
        matches = [edge for edge in self.outgoing.get(source, []) if edge.get("to") == target]
        if not matches:
            return None
        return matches[0]


class StatemRuntime:
    def __init__(self, options: RunOptions) -> None:
        self.options = options
        self.state_dir = options.state_dir.expanduser().resolve()

    def start(self, spec_path: str, *, fresh: bool = False) -> dict[str, Any]:
        spec = StatemSpec.load(spec_path)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "runs").mkdir(parents=True, exist_ok=True)

        requested_run_id = _clean_run_id(self.options.run_id) if self.options.run_id else None
        run_id = requested_run_id
        if run_id is None and not fresh:
            run_id = self._active_run_for_spec(spec)
        if run_id is None:
            run_id = _new_run_id()

        state_path = self._state_path(run_id)
        is_new = fresh or not state_path.exists()
        if is_new:
            state = {
                "version": 1,
                "run_id": run_id,
                "spec_path": str(spec.path),
                "spec_hash": spec.spec_hash,
                "current": spec.initial,
                "current_entry_id": _new_entry_id(),
                "created_at": _now(),
                "updated_at": _now(),
                "history": [],
            }
            self._ensure_agent_identity(state)
            self._ensure_entry_manifest(spec, state, spec.initial)
            _append_event(state, "start", {"current": spec.initial, "spec": str(spec.path)})
        else:
            state = _read_json(state_path)
            self._ensure_agent_identity(state)
            previous_current = str(state.get("current"))
            if previous_current not in spec.nodes:
                state["current"] = spec.initial
                state["current_entry_id"] = _new_entry_id()
                self._ensure_entry_manifest(spec, state, spec.initial)
                _append_event(
                    state,
                    "migrate_current",
                    {
                        "from": previous_current,
                        "to": spec.initial,
                        "reason": "current state missing from updated spec",
                    },
                )
            state["spec_path"] = str(spec.path)
            state["spec_hash"] = spec.spec_hash
            self._ensure_current_entry(spec, state)
            _append_event(state, "resume", {"current": state["current"], "spec": str(spec.path)})

        self._write_active(run_id)
        self._write_state(state)
        results = self._run_node_items(spec, state, str(state["current"]), "in_hook")
        _append_event(
            state,
            "in_hook",
            {"node": state["current"], "reason": "start" if is_new else "resume", "results": results},
        )
        self._write_state(state)
        _raise_if_blocked(
            results,
            f"Run '{run_id}' started, but in_hook failed for '{state['current']}'",
            details={
                "run_id": run_id,
                "current": state["current"],
                "stage": "in_hook",
                "results": results,
            },
        )

        return self.cur(run_id=run_id)

    def cur(self, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = state["current"]
        from .team import team_dir, team_summary

        return {
            "run_id": state["run_id"],
            "spec": str(spec.path),
            "spec_name": spec.name,
            "current": current,
            "current_entry_id": state.get("current_entry_id"),
            "agent_id": self._ensure_agent_identity(state),
            "dynamic_before_transfer": _dynamic_summary(
                spec.nodes[current].get(DYNAMIC_PURPOSE),
                self._dynamic_dir(state, current, str(state.get("current_entry_id"))),
            ),
            "multi_agent": team_summary(
                spec.nodes[current].get(TEAM_PURPOSE),
                team_dir(self.state_dir, state, current, str(state.get("current_entry_id")))
                if state.get("current_entry_id")
                else None,
            ),
            "prompt": spec.node_prompt(current),
            "before_transfer": _summaries(spec.nodes[current].get("before_transfer"), "before_transfer"),
            "state_hooks": self._active_state_hooks(spec, state),
            "next": [_edge_summary(edge) for edge in spec.outgoing.get(current, [])],
        }

    def graph_state(self, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        from .team import team_summary

        return {
            "run_id": state["run_id"],
            "current": state["current"],
            "current_entry_id": state.get("current_entry_id"),
            "nodes": [
                {
                    "name": name,
                    "prompt": spec.node_prompt(name),
                    "in_hook": _summaries(node.get("in_hook"), "in_hook"),
                    "before_transfer": _summaries(node.get("before_transfer"), "before_transfer"),
                    "dynamic_before_transfer": _dynamic_summary(node.get(DYNAMIC_PURPOSE), None),
                    "multi_agent": team_summary(node.get(TEAM_PURPOSE), None),
                    "out_hook": _summaries(node.get("out_hook"), "out_hook"),
                    "state_hooks": _state_hook_summaries(node.get(STATE_HOOKS_KEY)),
                }
                for name, node in spec.nodes.items()
            ],
            "edges": [_edge_summary(edge) for edge in spec.edges],
        }

    def node_details(self, node_name: str, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        if node_name not in spec.nodes:
            raise StatemError(f"Unknown node: {node_name}")
        node = spec.nodes[node_name]
        from .team import team_dir, team_summary

        return {
            "run_id": state["run_id"],
            "current": state["current"],
            "current_entry_id": state.get("current_entry_id"),
            "node": node_name,
            "prompt": spec.node_prompt(node_name),
            "in_hook": _summaries(node.get("in_hook"), "in_hook"),
            "before_transfer": _summaries(node.get("before_transfer"), "before_transfer"),
            "dynamic_before_transfer": _dynamic_summary(
                node.get(DYNAMIC_PURPOSE),
                self._dynamic_dir(state, node_name, str(state.get("current_entry_id")))
                if node_name == state["current"] and state.get("current_entry_id")
                else None,
            ),
            "multi_agent": team_summary(
                node.get(TEAM_PURPOSE),
                team_dir(self.state_dir, state, node_name, str(state.get("current_entry_id")))
                if node_name == state["current"] and state.get("current_entry_id")
                else None,
            ),
            "out_hook": _summaries(node.get("out_hook"), "out_hook"),
            "state_hooks": (
                self._active_state_hooks(spec, state)
                if node_name == state["current"]
                else _state_hook_summaries(node.get(STATE_HOOKS_KEY))
            ),
            "next": [_edge_summary(edge) for edge in spec.outgoing.get(node_name, [])],
        }

    def next_states(self, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = state["current"]
        return {
            "run_id": state["run_id"],
            "current": current,
            "next": [_edge_summary(edge) for edge in spec.outgoing.get(current, [])],
        }

    def goto(self, target: str, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        source = state["current"]
        edge = spec.edge_to(source, target)
        if edge is None:
            allowed = ", ".join(edge["to"] for edge in spec.outgoing.get(source, [])) or "(none)"
            raise StatemError(f"Cannot goto '{target}' from '{source}'. Allowed next states: {allowed}")

        self._ensure_current_entry(spec, state)
        attempt_details = self._begin_edge_attempt(state, source, target, edge)
        before_results = self._run_node_items(spec, state, source, "before_transfer")
        dynamic_payload = self._run_dynamic_before_transfer(spec, state, source, target)
        dynamic_results = dynamic_payload["results"]
        from .team import run_team_before_transfer

        team_payload = run_team_before_transfer(self, spec, state, source, target)
        team_results = team_payload["results"]
        condition_results = self._run_items(spec, state, edge.get("condition"), "condition")
        pre_results = before_results + dynamic_results + team_results + condition_results
        if _has_blocking_failure(pre_results):
            if _has_blocking_failure(before_results):
                stage = "before_transfer"
            elif _has_blocking_failure(dynamic_results):
                stage = DYNAMIC_PURPOSE
            elif _has_blocking_failure(team_results):
                stage = TEAM_PURPOSE
            elif _has_blocking_failure(condition_results):
                stage = "condition"
            else:
                stage = "before_transfer"
            details = _block_details(state, source, target, stage, pre_results)
            if attempt_details:
                details.update(attempt_details)
            if dynamic_payload:
                details[DYNAMIC_PURPOSE] = dynamic_payload
            if team_payload.get("configured"):
                details[TEAM_PURPOSE] = team_payload
            _append_event(
                state,
                "goto_blocked",
                details,
            )
            self._write_state(state)
            raise TransitionBlocked(
                f"Transition '{source}' -> '{target}' blocked before leaving '{source}'",
                details=details,
            )

        out_results = self._run_node_items(spec, state, source, "out_hook")
        edge_hook_results = self._run_items(spec, state, edge.get("hook"), "hook")
        side_effect_results = out_results + edge_hook_results
        if _has_blocking_failure(side_effect_results):
            details = _block_details(state, source, target, "out_hook", side_effect_results)
            if attempt_details:
                details.update(attempt_details)
            _append_event(
                state,
                "goto_blocked",
                details,
            )
            self._write_state(state)
            raise TransitionBlocked(
                f"Transition '{source}' -> '{target}' blocked while leaving '{source}'",
                details=details,
            )

        state["current"] = target
        state["current_entry_id"] = _new_entry_id()
        self._ensure_entry_manifest(spec, state, target)
        self._write_state(state)
        in_results = self._run_node_items(spec, state, target, "in_hook")
        all_results = pre_results + side_effect_results + in_results
        event_payload = {
            "from": source,
            "to": target,
            "before_transfer": before_results,
            "dynamic_before_transfer": dynamic_payload,
            "condition": condition_results,
            "out_hook": out_results,
            "edge_hook": edge_hook_results,
            "in_hook": in_results,
        }
        if attempt_details:
            event_payload.update(attempt_details)
        if team_payload.get("configured"):
            event_payload[TEAM_PURPOSE] = team_payload
        _append_event(state, "goto", event_payload)
        self._write_state(state)
        in_details = _block_details(state, source, target, "in_hook", in_results)
        if attempt_details:
            in_details.update(attempt_details)
        _raise_if_blocked(
            in_results,
            f"Entered '{target}', but in_hook failed",
            details=in_details,
        )
        payload = {
            "run_id": state["run_id"],
            "from": source,
            "to": target,
            "current": target,
            "current_entry_id": state.get("current_entry_id"),
            "results": all_results,
        }
        if attempt_details:
            payload.update(attempt_details)
        return payload

    def _begin_edge_attempt(
        self,
        state: dict[str, Any],
        source: str,
        target: str,
        edge: dict[str, Any],
    ) -> dict[str, int] | None:
        raw_limit = edge.get("max_attempts")
        if raw_limit is None:
            return None

        limit = int(raw_limit)
        entry_id = str(state.get("current_entry_id") or "")
        all_attempts = state.setdefault("edge_attempts", {})
        entry_attempts = all_attempts.setdefault(entry_id, {})
        source_attempts = entry_attempts.setdefault(source, {})
        used = int(source_attempts.get(target) or 0)
        if used >= limit:
            details = {
                "run_id": state["run_id"],
                "current": state["current"],
                "current_entry_id": state.get("current_entry_id"),
                "from": source,
                "to": target,
                "stage": "max_attempts",
                "results": [],
                "attempts_used": used,
                "max_attempts": limit,
                "attempts_remaining": 0,
                "summary": (
                    f"Edge attempt limit reached: {source} -> {target} "
                    f"used {used} of {limit} attempt(s) for the current node entry."
                ),
            }
            _append_event(state, "goto_blocked", details)
            self._write_state(state)
            raise TransitionBlocked(
                f"Transition '{source}' -> '{target}' reached max_attempts={limit}",
                details=details,
            )

        attempt = used + 1
        source_attempts[target] = attempt
        self._write_state(state)
        return {
            "attempt": attempt,
            "attempts_used": attempt,
            "max_attempts": limit,
            "attempts_remaining": limit - attempt,
        }

    def save(self, *, run_id: str | None = None, skip_hooks: bool = False) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = state["current"]
        results: list[dict[str, Any]] = []
        if not skip_hooks:
            results = self._run_node_items(spec, state, current, "out_hook")
        event = "save_blocked" if _has_blocking_failure(results) else "save"
        _append_event(state, event, {"node": current, "results": results, "skip_hooks": skip_hooks})
        self._write_state(state)
        _raise_if_blocked(
            results,
            f"Save blocked by out_hook for '{current}'",
            details={
                "run_id": state["run_id"],
                "current": current,
                "stage": "out_hook",
                "results": results,
            },
        )
        return {"run_id": state["run_id"], "current": current, "results": results}

    def history(self, *, run_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
        _spec, state = self._load_runtime(run_id)
        events = state.get("history", [])
        if limit is not None:
            events = events[-limit:]
        return {"run_id": state["run_id"], "current": state["current"], "history": events}

    def dynamic_path(self, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = str(state["current"])
        self._ensure_current_entry(spec, state)
        self._write_state(state)
        dynamic_dir = self._dynamic_dir(state, current, str(state["current_entry_id"]))
        dynamic_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_entry_manifest(spec, state, current)
        return {
            "run_id": state["run_id"],
            "current": current,
            "current_entry_id": state["current_entry_id"],
            "agent_id": self._ensure_agent_identity(state),
            "agent_role": self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or "",
            "path": str(dynamic_dir),
        }

    def dynamic_write(
        self,
        checks_file: str,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = str(state["current"])
        self._ensure_current_entry(spec, state)
        resolved_agent_id = _clean_agent_id(agent_id or self.options.agent_id or os.environ.get("STATEM_AGENT_ID") or "")
        if not resolved_agent_id:
            resolved_agent_id = self._ensure_agent_identity(state)
        resolved_role = role or self.options.agent_role or os.environ.get("STATEM_AGENT_ROLE") or ""
        source_path = Path(checks_file).expanduser().resolve()
        payload = _load_dynamic_check_file(source_path)
        normalized = _normalize_dynamic_payload(payload, resolved_agent_id, resolved_role)
        config = _normalize_dynamic_config(spec.nodes[current].get(DYNAMIC_PURPOSE))
        if config:
            _validate_dynamic_payload(normalized, config, source_path)

        dynamic_dir = self._dynamic_dir(state, current, str(state["current_entry_id"]))
        dynamic_dir.mkdir(parents=True, exist_ok=True)
        target_path = dynamic_dir / f"checks.{resolved_agent_id}.json"
        target_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = self._update_dynamic_manifest(
            spec,
            state,
            current,
            producer={
                "agent_id": resolved_agent_id,
                "role": resolved_role,
                "path": str(target_path),
                "updated_at": _now(),
            },
        )
        self._write_state(state)
        return {
            "run_id": state["run_id"],
            "current": current,
            "current_entry_id": state["current_entry_id"],
            "agent_id": resolved_agent_id,
            "role": resolved_role,
            "path": str(target_path),
            "checks": len(normalized["checks"]),
            "manifest": manifest,
        }

    def dynamic_list(self, *, run_id: str | None = None) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = str(state["current"])
        self._ensure_current_entry(spec, state)
        dynamic_dir = self._dynamic_dir(state, current, str(state["current_entry_id"]))
        files = sorted(dynamic_dir.glob("checks.*.json")) if dynamic_dir.exists() else []
        producers: list[dict[str, Any]] = []
        for path in files:
            try:
                payload = _load_dynamic_check_file(path)
                producer = _dynamic_payload_producer(payload)
                checks = _dynamic_payload_checks(payload)
            except StatemError as exc:
                producers.append({"path": str(path), "error": str(exc)})
                continue
            producers.append({"path": str(path), "producer": producer, "checks": len(checks)})
        manifest = self._read_dynamic_manifest(state, current, str(state["current_entry_id"]))
        return {
            "run_id": state["run_id"],
            "current": current,
            "current_entry_id": state["current_entry_id"],
            "path": str(dynamic_dir),
            "manifest": manifest,
            "producers": producers,
        }

    def team_init(self, tasks_file: str, *, run_id: str | None = None, entry_id: str | None = None) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).init(tasks_file, run_id=run_id, entry_id=entry_id)

    def team_status(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        include_results: bool = False,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).status(run_id=run_id, entry_id=entry_id, include_results=include_results)

    def team_prompt(
        self,
        task_id: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        command: str = "statem",
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).prompt(task_id, run_id=run_id, entry_id=entry_id, command=command)

    def team_claim(
        self,
        task_id: str | None = None,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        lease_seconds: int = 3600,
        worker_index: int | None = None,
        worker_count: int | None = None,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).claim(
            task_id,
            run_id=run_id,
            entry_id=entry_id,
            lease_seconds=lease_seconds,
            worker_index=worker_index,
            worker_count=worker_count,
        )

    def team_submit(
        self,
        task_id: str,
        result_file: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).submit(task_id, result_file, run_id=run_id, entry_id=entry_id)

    def team_report(
        self,
        task_id: str,
        report_file: str,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).report(task_id, report_file, run_id=run_id, entry_id=entry_id)

    def team_release(
        self,
        task_id: str | None = None,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        all_leased: bool = False,
        agent_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).release(
            task_id,
            run_id=run_id,
            entry_id=entry_id,
            all_leased=all_leased,
            agent_id=agent_id,
            reason=reason,
        )

    def team_advance(
        self, phase: str, *, run_id: str | None = None, entry_id: str | None = None
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).advance(phase, run_id=run_id, entry_id=entry_id)

    def team_reduce_input(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).reduce_input(run_id=run_id, entry_id=entry_id, output_file=output_file)

    def team_reduce(
        self,
        *,
        run_id: str | None = None,
        entry_id: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).reduce(run_id=run_id, entry_id=entry_id, strategy=strategy)

    def team_decide(
        self, decision_file: str, *, run_id: str | None = None, entry_id: str | None = None
    ) -> dict[str, Any]:
        from .team import TeamRunRuntime

        return TeamRunRuntime(self).decide(decision_file, run_id=run_id, entry_id=entry_id)

    def active_state_hooks(
        self,
        *,
        run_id: str | None = None,
        event: str | None = None,
        host: str | None = None,
    ) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        return {
            "run_id": state["run_id"],
            "current": state["current"],
            "current_entry_id": state.get("current_entry_id"),
            "event": event or "",
            "host": host or "",
            "hooks": self._active_state_hooks(spec, state, event=event, host=host),
        }

    def run_state_hooks(
        self,
        event: str,
        *,
        run_id: str | None = None,
        host: str | None = None,
        command: str = "statem",
    ) -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        event_name = str(event).strip()
        if not event_name:
            raise StatemError("state hook event is required")

        hooks = self._active_state_hooks(spec, state, event=event_name, host=host)
        results = [self._run_state_hook(spec, state, hook, event_name, command) for hook in hooks]
        decision = "block" if any(result.get("decision") == "block" for result in results) else "allow"
        reason = "\n\n".join(str(result.get("reason") or "") for result in results if result.get("decision") == "block")
        payload = {
            "run_id": state["run_id"],
            "current": state["current"],
            "current_entry_id": state.get("current_entry_id"),
            "event": event_name,
            "host": host or "",
            "matched_hooks": len(hooks),
            "decision": decision,
            "reason": reason,
            "hooks": hooks,
            "results": results,
        }
        if hooks:
            history_payload = dict(payload)
            history_payload["hook_event"] = history_payload.pop("event")
            _append_event(state, STATE_HOOK_PURPOSE, history_payload)
            self._write_state(state)
        return payload

    def prompt(self, *, run_id: str | None = None, command: str = "statem") -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = state["current"]
        state_dir = self.state_dir
        run_id_value = state["run_id"]
        spec_arg = shlex.quote(str(spec.path))
        state_dir_arg = shlex.quote(str(state_dir))
        run_id_arg = shlex.quote(str(run_id_value))
        prompt = f"""You are resuming a statem-managed agent run after a context clear.

Treat statem as the source of truth for workflow state. Do not rely on prior chat context.

Run these commands first:

{command} start {spec_arg} --run-id {run_id_arg} --state-dir {state_dir_arg} --json
{command} cur --run-id {run_id_arg} --state-dir {state_dir_arg} --json
{command} history --run-id {run_id_arg} --state-dir {state_dir_arg} --tail 8 --json

Then follow the current node prompt and only move with:

{command} goto <next-state> --run-id {run_id_arg} --state-dir {state_dir_arg} --json

Current state at prompt generation time: {current}
"""
        return {
            "run_id": run_id_value,
            "current": current,
            "spec": str(spec.path),
            "state_dir": str(state_dir),
            "prompt": prompt.strip() + "\n",
        }

    def compact_prompt(self, *, run_id: str | None = None, command: str = "statem") -> dict[str, Any]:
        spec, state = self._load_runtime(run_id)
        current = state["current"]
        state_dir = self.state_dir
        run_id_value = state["run_id"]
        state_dir_arg = shlex.quote(str(state_dir))
        run_id_arg = shlex.quote(str(run_id_value))
        prompt = f"""/compact Keep only the durable state needed to continue this statem-managed run.

Run identity:
- Use exactly this statem run id: {run_id_value}
- Ignore every older statem run id, stale statem command, or run id remembered from prior chat.
- Do not carry forward any command that uses a different --run-id.

Retain:
- current statem node: {current}
- statem spec path: {spec.path}
- current plan, accepted implementation facts, verification status, and open risks
- progress.md facts and any explicit user decisions
- the instruction that statem is the source of truth for workflow state

Discard:
- stale failed attempts that were superseded
- duplicate tool output and noisy intermediate reasoning
- old plans that no longer match progress.md or the current statem state
- irrelevant conversation before the current loop

After compaction, immediately recover with:

{command} cur --run-id {run_id_arg} --state-dir {state_dir_arg} --json
{command} history --run-id {run_id_arg} --state-dir {state_dir_arg} --tail 8 --json
"""
        return {
            "run_id": run_id_value,
            "current": current,
            "spec": str(spec.path),
            "state_dir": str(state_dir),
            "prompt": prompt.strip() + "\n",
        }

    def _run_node_items(
        self, spec: StatemSpec, state: dict[str, Any], node_name: str, key: str
    ) -> list[dict[str, Any]]:
        return self._run_items(spec, state, spec.nodes[node_name].get(key), key)

    def _active_state_hooks(
        self,
        spec: StatemSpec,
        state: dict[str, Any],
        *,
        event: str | None = None,
        host: str | None = None,
    ) -> list[dict[str, Any]]:
        current = str(state["current"])
        self._ensure_current_entry(spec, state)
        hooks = _state_hook_summaries(spec.nodes[current].get(STATE_HOOKS_KEY))
        filtered: list[dict[str, Any]] = []
        for hook in hooks:
            if event and hook["event"] != event:
                continue
            if host and not _state_hook_matches_host(hook, host):
                continue
            filtered.append(
                {
                    **hook,
                    "run_id": state["run_id"],
                    "node": current,
                    "entry_id": state.get("current_entry_id"),
                    "active": True,
                }
            )
        return filtered

    def _run_state_hook(
        self,
        spec: StatemSpec,
        state: dict[str, Any],
        hook: dict[str, Any],
        event: str,
        command: str,
    ) -> dict[str, Any]:
        template = str(hook.get("template") or "")
        if template == "statem_autoloop":
            return self._run_state_hook_autoloop(spec, state, hook, event, command)
        return {
            "name": hook.get("name"),
            "event": event,
            "template": template,
            "decision": "allow",
            "reason": f"unsupported state hook template {template!r}; allowing",
        }

    def _run_state_hook_autoloop(
        self,
        spec: StatemSpec,
        state: dict[str, Any],
        hook: dict[str, Any],
        event: str,
        command: str,
    ) -> dict[str, Any]:
        current = str(state["current"])
        next_edges = spec.outgoing.get(current, [])
        stop_states = set(hook.get("stop_states") or DEFAULT_STOP_STATES)
        if event != "stop" or current in stop_states or not next_edges:
            return {
                "name": hook.get("name"),
                "event": event,
                "template": hook.get("template"),
                "decision": "allow",
                "reason": "",
            }
        reason = _state_hook_autoloop_reason(
            hook,
            command,
            self.state_dir,
            str(state["run_id"]),
            current,
            str(state.get("current_entry_id") or ""),
            next_edges,
        )
        return {
            "name": hook.get("name"),
            "event": event,
            "template": hook.get("template"),
            "decision": "block",
            "reason": reason,
        }

    def _run_items(
        self, spec: StatemSpec, state: dict[str, Any], raw_items: Any, purpose: str
    ) -> list[dict[str, Any]]:
        items = _normalize_items(raw_items, purpose)
        return [self._run_item(spec, state, item, purpose) for item in items]

    def _run_item(
        self, spec: StatemSpec, state: dict[str, Any], item: dict[str, Any], purpose: str
    ) -> dict[str, Any]:
        item_type = item["type"]
        if item_type == "message":
            text = str(item.get("text") or item.get("prompt") or "")
            self.options.emit(text)
            return _result(item, purpose, True, output=text)
        if item_type == "manual":
            return self._run_manual(item, purpose)
        if item_type == "checklist":
            return self._run_checklist(item, purpose)
        if item_type == "command":
            return self._run_command(spec, state, item, purpose)
        if item_type == "predicate":
            return self._run_predicate(spec, item, purpose)
        if item_type == "llm_review":
            return self._run_llm_review(spec, state, item, purpose)
        return _result(item, purpose, False, output=f"Unsupported item type: {item_type}")

    def _run_manual(self, item: dict[str, Any], purpose: str) -> dict[str, Any]:
        prompt = str(item.get("prompt") or item.get("text") or item.get("name") or "Confirm check")
        self.options.emit(prompt)
        confirmation = _confirmation_mode(item)
        if confirmation == "none":
            return _result(item, purpose, True, output="manual confirmation not required by spec")
        if self.options.yes:
            return _result(item, purpose, True, output="auto-confirmed yes")
        if not sys.stdin.isatty():
            return _result(
                item,
                purpose,
                False,
                output=(
                    "manual confirmation required for this item; rerun with --yes only after "
                    "verifying the prompt"
                ),
            )
        answer = input("Confirm? [y/N] ").strip().lower()
        return _result(item, purpose, answer in {"y", "yes"}, output=f"answered {answer or 'no'}")

    def _run_checklist(self, item: dict[str, Any], purpose: str) -> dict[str, Any]:
        entries = item.get("items") or item.get("checks") or []
        if not isinstance(entries, list) or not entries:
            return _result(item, purpose, False, output="checklist requires a non-empty items list")
        for entry in entries:
            self.options.emit(f"- {entry}")
        confirmation = _confirmation_mode(item)
        if confirmation == "none":
            return _result(item, purpose, True, output="checklist confirmation not required by spec")
        if self.options.yes:
            return _result(item, purpose, True, output="auto-confirmed checklist")
        if not sys.stdin.isatty():
            preview = "; ".join(str(entry) for entry in entries[:3])
            if len(entries) > 3:
                preview += f"; ... ({len(entries)} items)"
            return _result(
                item,
                purpose,
                False,
                output=(
                    "checklist confirmation required; rerun with --yes only after confirming: "
                    + preview
                ),
            )
        for entry in entries:
            answer = input(f"Confirm '{entry}'? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                return _result(item, purpose, False, output=f"unchecked: {entry}")
        return _result(item, purpose, True, output="checklist confirmed")

    def _run_command(
        self, spec: StatemSpec, state: dict[str, Any], item: dict[str, Any], purpose: str
    ) -> dict[str, Any]:
        command = str(item.get("run") or "")
        if not command:
            return _result(item, purpose, False, output="command item requires 'run'")
        cwd = _resolve_cwd(spec, item)
        timeout = item.get("timeout")
        self.options.emit(f"$ {command}")
        env = _hook_env(
            spec,
            state,
            self.state_dir,
            purpose,
            agent_id=self.options.agent_id,
            agent_role=self.options.agent_role,
        )
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                timeout=float(timeout) if timeout is not None else None,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _result(item, purpose, False, output=f"command timed out after {timeout}s")

        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        if output:
            self.options.emit(output)
        return _result(item, purpose, completed.returncode == 0, output=output, exit_code=completed.returncode)

    def _run_llm_review(
        self, spec: StatemSpec, state: dict[str, Any], item: dict[str, Any], purpose: str
    ) -> dict[str, Any]:
        command = str(item.get("run") or os.environ.get("STATEM_LLM_REVIEW_CMD") or "")
        prompt = _review_prompt(spec, state, item, purpose)
        if not command:
            fallback = dict(item)
            fallback["prompt"] = (
                "No llm_review command was configured. Manually confirm this review instead.\n\n" + prompt
            )
            return self._run_manual(fallback, purpose)

        cwd = _resolve_cwd(spec, item)
        timeout = item.get("timeout")
        self.options.emit(f"$ {command}")
        env = _hook_env(
            spec,
            state,
            self.state_dir,
            purpose,
            agent_id=self.options.agent_id,
            agent_role=self.options.agent_role,
        )
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                timeout=float(timeout) if timeout is not None else None,
                input=prompt if item.get("stdin", True) is not False else None,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _result(item, purpose, False, output=f"llm_review command timed out after {timeout}s")

        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        problems: list[str] = []
        if completed.returncode != 0:
            problems.append(f"review command exited {completed.returncode}")
        if "accept_contains" in item and str(item["accept_contains"]) not in output:
            problems.append(f"review output did not contain {item['accept_contains']!r}")
        if "reject_contains" in item and str(item["reject_contains"]) in output:
            problems.append(f"review output contained rejected text {item['reject_contains']!r}")
        if "accept_regex" in item and re.search(str(item["accept_regex"]), output) is None:
            problems.append(f"review output did not match regex {item['accept_regex']!r}")
        if "reject_regex" in item and re.search(str(item["reject_regex"]), output) is not None:
            problems.append(f"review output matched rejected regex {item['reject_regex']!r}")

        result_output = output
        if problems:
            result_output = "; ".join(problems + ([output] if output else []))
        if output:
            self.options.emit(output)
        return _result(item, purpose, not problems, output=result_output, exit_code=completed.returncode)

    def _run_predicate(self, spec: StatemSpec, item: dict[str, Any], purpose: str) -> dict[str, Any]:
        path_value = item.get("path")
        if not path_value:
            return _result(item, purpose, False, output="predicate requires 'path'")
        path = _resolve_path(spec, item, str(path_value))
        problems: list[str] = []

        expected_exists = item.get("exists")
        if expected_exists is not None and path.exists() != bool(expected_exists):
            problems.append(f"exists expected {bool(expected_exists)}, got {path.exists()}")

        needs_file = any(key in item for key in ("non_empty", "contains", "not_contains", "matches", "json_path"))
        if needs_file and not path.exists():
            problems.append(f"file does not exist: {path}")
        elif path.exists():
            if item.get("non_empty") is True and path.stat().st_size == 0:
                problems.append("file is empty")
            if "contains" in item or "not_contains" in item or "matches" in item:
                text = path.read_text(encoding="utf-8")
                if "contains" in item and str(item["contains"]) not in text:
                    problems.append(f"file does not contain {item['contains']!r}")
                if "not_contains" in item and str(item["not_contains"]) in text:
                    problems.append(f"file contains forbidden text {item['not_contains']!r}")
                if "matches" in item and re.search(str(item["matches"]), text) is None:
                    problems.append(f"file does not match regex {item['matches']!r}")
            if "json_path" in item:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    found, value = _json_path(data, str(item["json_path"]))
                except json.JSONDecodeError as exc:
                    problems.append(f"invalid json: {exc}")
                else:
                    if not found:
                        problems.append(f"json path not found: {item['json_path']}")
                    elif "equals" in item and value != item["equals"]:
                        problems.append(f"json path {item['json_path']} expected {item['equals']!r}, got {value!r}")
                    elif "one_of" in item and value not in item["one_of"]:
                        problems.append(f"json path {item['json_path']} value {value!r} not in {item['one_of']!r}")

        output = "; ".join(problems) if problems else f"predicate passed for {path}"
        if problems:
            self.options.emit(output)
        return _result(item, purpose, not problems, output=output)

    def _run_dynamic_before_transfer(
        self, spec: StatemSpec, state: dict[str, Any], source: str, target: str
    ) -> dict[str, Any]:
        config = _normalize_dynamic_config(spec.nodes[source].get(DYNAMIC_PURPOSE))
        if not config:
            return {"configured": False, "results": []}

        entry_id = str(state.get("current_entry_id") or "")
        dynamic_dir = self._dynamic_dir(state, source, entry_id)
        confirmation_results: list[dict[str, Any]] = []
        if config.get("stale_policy") == "require_confirmation":
            confirmation_results = self._run_items(
                spec,
                state,
                {
                    "type": "manual",
                    "prompt": (
                        f"Confirm {DYNAMIC_PURPOSE} checks for entry {entry_id} "
                        "were refreshed for the latest implementation approach."
                    ),
                },
                DYNAMIC_PURPOSE,
            )
            if _has_blocking_failure(confirmation_results):
                payload = {
                    "configured": True,
                    "path": str(dynamic_dir),
                    "entry_id": entry_id,
                    "producers": [],
                    "checks_snapshot": [],
                    "results": confirmation_results,
                }
                _append_event(
                    state,
                    DYNAMIC_PURPOSE,
                    {"node": source, "to": target, **payload},
                )
                return payload

        loaded = self._load_dynamic_checks(spec, state, source, config, dynamic_dir)
        results = (
            confirmation_results
            + loaded.get("load_results", [])
            + self._run_items(spec, state, loaded["checks"], DYNAMIC_PURPOSE)
        )
        payload = {
            "configured": True,
            "path": str(dynamic_dir),
            "entry_id": entry_id,
            "producers": loaded["producers"],
            "checks_snapshot": loaded["checks"],
            "results": results,
        }
        _append_event(
            state,
            DYNAMIC_PURPOSE,
            {"node": source, "to": target, **payload},
        )
        return payload

    def _load_dynamic_checks(
        self,
        spec: StatemSpec,
        state: dict[str, Any],
        node_name: str,
        config: dict[str, Any],
        dynamic_dir: Path,
    ) -> dict[str, Any]:
        if config.get("path") != "current_entry":
            raise StatemError(f"{DYNAMIC_PURPOSE} only supports path: current_entry")

        files = sorted(dynamic_dir.glob("checks.*.json")) if dynamic_dir.exists() else []
        problems: list[str] = []
        producers: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        manifest = self._read_dynamic_manifest(state, node_name, str(state.get("current_entry_id") or ""))
        for producer in manifest.get("producers", []):
            producer_path = Path(str(producer.get("path") or ""))
            if producer_path and not producer_path.exists():
                problems.append(
                    f"{DYNAMIC_PURPOSE} producer {producer.get('agent_id') or '(unknown)'} "
                    f"was registered but its checks file is missing: {producer_path}"
                )
        for path in files:
            try:
                raw_payload = _load_dynamic_check_file(path)
                payload = _normalize_dynamic_payload(
                    raw_payload,
                    _clean_agent_id(_dynamic_payload_producer(raw_payload).get("agent_id") or _checks_file_agent_id(path)),
                    str(_dynamic_payload_producer(raw_payload).get("role") or ""),
                )
                producer = payload["producer"]
                item_checks = payload["checks"]
                _validate_dynamic_payload(payload, config, path)
            except StatemError as exc:
                problems.append(str(exc))
                continue
            producers.append({"agent_id": producer.get("agent_id"), "role": producer.get("role"), "path": str(path)})
            checks.extend(item_checks)

        if config.get("required") and not files:
            problems.append(f"{DYNAMIC_PURPOSE} requires at least one checks.<agent-id>.json file in {dynamic_dir}")
        min_items = int(config.get("min_items") or 0)
        if len(checks) < min_items:
            problems.append(f"{DYNAMIC_PURPOSE} requires at least {min_items} check item(s), found {len(checks)}")

        if problems:
            synthetic = _result(
                {"type": "manual", "blocking": True, "on_failure": "block"},
                DYNAMIC_PURPOSE,
                False,
                output="; ".join(problems),
            )
            return {"producers": producers, "checks": [], "load_results": [synthetic]}
        return {"producers": producers, "checks": checks, "load_results": []}

    def _load_runtime(self, run_id: str | None = None) -> tuple[StatemSpec, dict[str, Any]]:
        selected_run_id = _clean_run_id(run_id or self.options.run_id) if (run_id or self.options.run_id) else None
        if selected_run_id is None:
            selected_run_id = self._read_active()
        state_path = self._state_path(selected_run_id)
        if not state_path.exists():
            raise StatemError(f"Run not found: {selected_run_id}")
        state = _read_json(state_path)
        spec = StatemSpec.load(state["spec_path"])
        if state.get("current") not in spec.nodes:
            raise StatemError(
                f"Run '{selected_run_id}' points at '{state.get('current')}', which is not in the current spec"
            )
        previous_agent_id = state.get("agent_id")
        previous_entry_id = state.get("current_entry_id")
        self._ensure_agent_identity(state)
        self._ensure_current_entry(spec, state)
        if state.get("agent_id") != previous_agent_id or state.get("current_entry_id") != previous_entry_id:
            self._write_state(state)
        return spec, state

    def _ensure_agent_identity(self, state: dict[str, Any]) -> str:
        configured = _clean_agent_id(self.options.agent_id or os.environ.get("STATEM_AGENT_ID") or "")
        if configured:
            if not state.get("agent_id"):
                state["agent_id"] = configured
            return configured
        existing = _clean_agent_id(str(state.get("agent_id") or ""))
        if existing:
            return existing
        generated = _new_agent_id()
        state["agent_id"] = generated
        return generated

    def _ensure_current_entry(self, spec: StatemSpec, state: dict[str, Any]) -> None:
        current = str(state.get("current") or "")
        if not state.get("current_entry_id"):
            state["current_entry_id"] = _new_entry_id()
        self._ensure_entry_manifest(spec, state, current)

    def _dynamic_dir(self, state: dict[str, Any], node_name: str, entry_id: str) -> Path:
        return self.state_dir / "runs" / _clean_run_id(str(state["run_id"])) / "nodes" / _clean_node_id(node_name) / entry_id / DYNAMIC_PURPOSE

    def _entry_manifest_path(self, state: dict[str, Any], node_name: str, entry_id: str) -> Path:
        return self._dynamic_dir(state, node_name, entry_id) / "manifest.json"

    def _ensure_entry_manifest(self, spec: StatemSpec, state: dict[str, Any], node_name: str) -> dict[str, Any]:
        entry_id = str(state.get("current_entry_id") or _new_entry_id())
        state["current_entry_id"] = entry_id
        dynamic_dir = self._dynamic_dir(state, node_name, entry_id)
        dynamic_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._entry_manifest_path(state, node_name, entry_id)
        if manifest_path.exists():
            return _read_json(manifest_path)
        from .team import team_summary

        manifest = {
            "version": 1,
            "run_id": state["run_id"],
            "node": node_name,
            "entry_id": entry_id,
            "created_at": _now(),
            "dynamic_before_transfer": _dynamic_summary(spec.nodes[node_name].get(DYNAMIC_PURPOSE), dynamic_dir),
            "multi_agent": team_summary(spec.nodes[node_name].get(TEAM_PURPOSE), None),
            "state_hooks": _state_hook_summaries(spec.nodes[node_name].get(STATE_HOOKS_KEY)),
            "producers": [],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest

    def _read_dynamic_manifest(self, state: dict[str, Any], node_name: str, entry_id: str) -> dict[str, Any]:
        manifest_path = self._entry_manifest_path(state, node_name, entry_id)
        if not manifest_path.exists():
            return {}
        return _read_json(manifest_path)

    def _update_dynamic_manifest(
        self, spec: StatemSpec, state: dict[str, Any], node_name: str, producer: dict[str, Any]
    ) -> dict[str, Any]:
        manifest = self._ensure_entry_manifest(spec, state, node_name)
        producers = [item for item in manifest.get("producers", []) if item.get("agent_id") != producer.get("agent_id")]
        producers.append(producer)
        manifest["producers"] = producers
        manifest["updated_at"] = _now()
        manifest_path = self._entry_manifest_path(state, node_name, str(state["current_entry_id"]))
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest

    def _active_run_for_spec(self, spec: StatemSpec) -> str | None:
        try:
            run_id = self._read_active()
        except StatemError:
            return None
        state_path = self._state_path(run_id)
        if not state_path.exists():
            return None
        state = _read_json(state_path)
        if Path(str(state.get("spec_path", ""))).expanduser().resolve() == spec.path:
            return run_id
        return None

    def _read_active(self) -> str:
        active_path = self.state_dir / "active_run"
        if not active_path.exists():
            raise StatemError("No active run. Start one with: statem start SPEC")
        run_id = active_path.read_text(encoding="utf-8").strip()
        if not run_id:
            raise StatemError("Active run file is empty. Start a run again.")
        return run_id

    def _write_active(self, run_id: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "active_run").write_text(run_id + "\n", encoding="utf-8")

    def _state_path(self, run_id: str) -> Path:
        return self.state_dir / "runs" / _clean_run_id(run_id) / "state.json"

    def _write_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        path = self._state_path(str(state["run_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)


def validate_spec(path: str, *, strict: bool = False) -> dict[str, Any]:
    spec = StatemSpec.load(path, strict=strict)
    payload = {
        "ok": True,
        "spec": str(spec.path),
        "name": spec.name,
        "initial": spec.initial,
        "nodes": list(spec.nodes),
        "edges": [
            {
                "from": edge["from"],
                "to": edge["to"],
                **({"max_attempts": edge["max_attempts"]} if "max_attempts" in edge else {}),
            }
            for edge in spec.edges
        ],
    }
    if strict:
        payload["strict"] = True
    return payload


def _validate_edge_max_attempts(edge: dict[str, Any], label: str) -> list[str]:
    if "max_attempts" not in edge:
        return []
    value = edge["max_attempts"]
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{label}: max_attempts must be a positive integer"]
    if value <= 0:
        return [f"{label}: max_attempts must be a positive integer"]
    return []


def _strict_keyword_errors(raw: dict[str, Any]) -> list[str]:
    errors = _unknown_keyword_errors(raw, STRICT_ROOT_KEYS, "root")

    raw_nodes = raw.get("nodes")
    if isinstance(raw_nodes, dict):
        for name, raw_node in raw_nodes.items():
            if isinstance(raw_node, dict):
                errors.extend(_strict_node_keyword_errors(raw_node, f"node {name!r}"))
    elif isinstance(raw_nodes, list):
        for index, raw_node in enumerate(raw_nodes, start=1):
            if isinstance(raw_node, dict):
                name = raw_node.get("name", index)
                errors.extend(_strict_node_keyword_errors(raw_node, f"node {name!r}"))

    raw_edges = raw.get("edges")
    if isinstance(raw_edges, list):
        for index, raw_edge in enumerate(raw_edges, start=1):
            if isinstance(raw_edge, dict):
                source = raw_edge.get("from") or raw_edge.get("source") or raw_edge.get("node1") or "?"
                target = raw_edge.get("to") or raw_edge.get("target") or raw_edge.get("node2") or "?"
                errors.extend(
                    _strict_edge_keyword_errors(
                        raw_edge,
                        f"edge {index} {source}->{target}",
                        nested=False,
                    )
                )
    return errors


def _strict_node_keyword_errors(node: dict[str, Any], label: str) -> list[str]:
    errors = _unknown_keyword_errors(node, STRICT_NODE_KEYS, label)
    for purpose in ("in_hook", "before_transfer", "out_hook"):
        errors.extend(_strict_item_keyword_errors(node.get(purpose), purpose, f"{label} {purpose}"))

    dynamic = node.get(DYNAMIC_PURPOSE)
    if isinstance(dynamic, dict):
        errors.extend(_unknown_keyword_errors(dynamic, STRICT_DYNAMIC_CONFIG_KEYS, f"{label} {DYNAMIC_PURPOSE}"))

    team = node.get(TEAM_PURPOSE)
    if isinstance(team, dict):
        errors.extend(_unknown_keyword_errors(team, STRICT_TEAM_CONFIG_KEYS, f"{label} {TEAM_PURPOSE}"))
        reducer = team.get("reducer")
        if isinstance(reducer, dict):
            errors.extend(
                _unknown_keyword_errors(
                    reducer,
                    STRICT_TEAM_REDUCER_KEYS,
                    f"{label} {TEAM_PURPOSE}.reducer",
                )
            )
        for schema_name in ("task_schema", "result_schema"):
            schema = team.get(schema_name)
            if isinstance(schema, dict):
                errors.extend(
                    _unknown_keyword_errors(
                        schema,
                        STRICT_TEAM_SCHEMA_KEYS,
                        f"{label} {TEAM_PURPOSE}.{schema_name}",
                    )
                )

    raw_hooks = node.get(STATE_HOOKS_KEY)
    hooks = raw_hooks if isinstance(raw_hooks, list) else [raw_hooks] if raw_hooks is not None else []
    for index, hook in enumerate(hooks, start=1):
        if isinstance(hook, dict):
            errors.extend(
                _unknown_keyword_errors(
                    hook,
                    STRICT_STATE_HOOK_KEYS,
                    f"{label} {STATE_HOOKS_KEY}[{index}]",
                )
            )

    raw_next = node.get("next_states", node.get("next"))
    next_edges = raw_next if isinstance(raw_next, list) else [raw_next] if raw_next is not None else []
    for index, edge in enumerate(next_edges, start=1):
        if isinstance(edge, dict):
            errors.extend(
                _strict_edge_keyword_errors(
                    edge,
                    f"{label} next[{index}]",
                    nested=True,
                )
            )
    return errors


def _strict_edge_keyword_errors(edge: dict[str, Any], label: str, *, nested: bool) -> list[str]:
    allowed = STRICT_NESTED_EDGE_KEYS if nested else STRICT_EDGE_KEYS
    errors = _unknown_keyword_errors(edge, allowed, label)
    errors.extend(_strict_item_keyword_errors(edge.get("condition"), "condition", f"{label} condition"))
    errors.extend(_strict_item_keyword_errors(edge.get("hook"), "hook", f"{label} hook"))
    return errors


def _strict_item_keyword_errors(raw_items: Any, purpose: str, label: str) -> list[str]:
    items = raw_items if isinstance(raw_items, list) else [raw_items] if raw_items is not None else []
    errors: list[str] = []
    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            continue
        try:
            item_type = str(_normalize_item(raw_item, purpose)["type"])
        except StatemError:
            continue
        allowed = STRICT_CHECK_KEYS.get(item_type)
        if allowed is None:
            allowed = set().union(*STRICT_CHECK_KEYS.values())
        errors.extend(_unknown_keyword_errors(raw_item, allowed, f"{label}[{index}]"))
    return errors


def _unknown_keyword_errors(
    mapping: dict[str, Any],
    allowed: set[str],
    label: str,
) -> list[str]:
    errors: list[str] = []
    for raw_key in mapping:
        key = str(raw_key)
        if isinstance(raw_key, str) and raw_key in allowed:
            continue
        suggestion = difflib.get_close_matches(key, sorted(allowed), n=1, cutoff=0.72)
        message = f"{label}: unknown keyword {key!r}"
        if suggestion:
            message += f"; did you mean {suggestion[0]!r}?"
        errors.append(message)
    return errors


def _load_mapping(text: str, path: Path) -> dict[str, Any]:
    try:
        data = json.loads(text) if path.suffix.lower() == ".json" else miniyaml.loads(text)
    except Exception as exc:
        raise StatemError(f"Could not parse {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise StatemError(f"Spec root must be a mapping, got {type(data).__name__}")
    return data


def _normalize_nodes(raw_nodes: Any) -> dict[str, dict[str, Any]]:
    if raw_nodes is None:
        return {}
    nodes: dict[str, dict[str, Any]] = {}
    if isinstance(raw_nodes, dict):
        for name, raw_node in raw_nodes.items():
            nodes[str(name)] = _normalize_node(str(name), raw_node)
        return nodes
    if isinstance(raw_nodes, list):
        for raw_node in raw_nodes:
            if isinstance(raw_node, str):
                nodes[raw_node] = {"name": raw_node}
                continue
            if not isinstance(raw_node, dict) or "name" not in raw_node:
                raise StatemError("List-style nodes must be strings or mappings with a name")
            name = str(raw_node["name"])
            nodes[name] = _normalize_node(name, raw_node)
        return nodes
    raise StatemError("nodes must be a mapping or list")


def _normalize_node(name: str, raw_node: Any) -> dict[str, Any]:
    if raw_node is None:
        node: dict[str, Any] = {}
    elif isinstance(raw_node, str):
        node = {"prompt": raw_node}
    elif isinstance(raw_node, dict):
        node = dict(raw_node)
    else:
        raise StatemError(f"Node '{name}' must be a mapping or string")
    node["name"] = name
    return node


def _normalize_edges(raw: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for source, node in nodes.items():
        next_states = node.get("next_states") or node.get("next")
        if next_states is None:
            continue
        if not isinstance(next_states, list):
            next_states = [next_states]
        for item in next_states:
            edge = _edge_from_next_state(source, item)
            edges.append(edge)

    raw_edges = raw.get("edges") or []
    if not isinstance(raw_edges, list):
        raise StatemError("edges must be a list")
    for item in raw_edges:
        if not isinstance(item, dict):
            raise StatemError("Each edge must be a mapping")
        edge = dict(item)
        edge["from"] = str(edge.get("from") or edge.get("source") or edge.get("node1") or "")
        edge["to"] = str(edge.get("to") or edge.get("target") or edge.get("node2") or "")
        if not edge["from"] or not edge["to"]:
            raise StatemError("Each edge must define from/to")
        edges.append(edge)
    return edges


def _edge_from_next_state(source: str, item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"from": source, "to": item}
    if isinstance(item, dict):
        edge = dict(item)
        target = edge.get("to") or edge.get("target") or edge.get("name")
        if not target:
            raise StatemError(f"next_states item for '{source}' must include to/target")
        edge["from"] = source
        edge["to"] = str(target)
        return edge
    raise StatemError(f"next_states item for '{source}' must be a string or mapping")


def _normalize_items(raw_items: Any, purpose: str) -> list[dict[str, Any]]:
    if raw_items is None or raw_items == "":
        return []
    if isinstance(raw_items, list):
        return [_normalize_item(item, purpose) for item in raw_items]
    return [_normalize_item(raw_items, purpose)]


def _normalize_item(raw_item: Any, purpose: str) -> dict[str, Any]:
    if isinstance(raw_item, str):
        return _with_defaults({"type": "manual", "prompt": raw_item}, purpose)
    if not isinstance(raw_item, dict):
        return _with_defaults({"type": "message", "text": str(raw_item)}, purpose)

    item = dict(raw_item)
    if "cmd" in item and "run" not in item:
        item["run"] = item["cmd"]
    if "command" in item and "run" not in item:
        item["run"] = item["command"]
    if "type" not in item:
        if "run" in item:
            item["type"] = "command"
        elif "path" in item:
            item["type"] = "predicate"
        elif "items" in item or "checks" in item:
            item["type"] = "checklist"
        elif purpose in GATING_PURPOSES:
            item["type"] = "manual"
        else:
            item["type"] = "message"
    item["type"] = str(item["type"])
    return _with_defaults(item, purpose)


def _with_defaults(item: dict[str, Any], purpose: str) -> dict[str, Any]:
    item_type = item["type"]
    if "blocking" not in item:
        item["blocking"] = purpose in GATING_PURPOSES or item_type in {
            "manual",
            "checklist",
            "command",
            "predicate",
            "llm_review",
        }
    if "on_failure" not in item:
        item["on_failure"] = "block" if bool(item["blocking"]) else "continue"
    return item


def _validate_items(raw_items: Any, purpose: str, label: str) -> list[str]:
    errors: list[str] = []
    try:
        items = _normalize_items(raw_items, purpose)
    except StatemError as exc:
        return [f"{label}: {exc}"]
    for item in items:
        item_type = item["type"]
        if item_type not in {"message", "manual", "checklist", "command", "predicate", "llm_review"}:
            errors.append(f"{label}: unsupported type '{item_type}'")
        if item_type == "command" and not item.get("run"):
            errors.append(f"{label}: command requires run")
        if item_type == "predicate" and not item.get("path"):
            errors.append(f"{label}: predicate requires path")
        if item_type == "checklist" and not (item.get("items") or item.get("checks")):
            errors.append(f"{label}: checklist requires items")
        if item_type in {"manual", "checklist"}:
            try:
                _confirmation_mode(item)
            except StatemError as exc:
                errors.append(f"{label}: {exc}")
        if item.get("on_failure") not in {"block", "continue"}:
            errors.append(f"{label}: on_failure must be 'block' or 'continue'")
    return errors


def _confirmation_mode(item: dict[str, Any]) -> str:
    raw_value = item.get("confirmation", item.get("confirm", "required"))
    if isinstance(raw_value, bool):
        return "required" if raw_value else "none"
    value = str(raw_value).strip().lower().replace("-", "_")
    aliases = {
        "": "required",
        "required": "required",
        "human": "required",
        "manual": "required",
        "true": "required",
        "yes": "required",
        "confirm": "required",
        "none": "none",
        "no": "none",
        "false": "none",
        "off": "none",
        "advisory": "none",
        "message": "none",
    }
    mode = aliases.get(value)
    if not mode:
        raise StatemError("confirmation must be 'required' or 'none'")
    return mode


def _normalize_state_hooks(raw_hooks: Any) -> list[dict[str, Any]]:
    if raw_hooks is None or raw_hooks == "":
        return []
    if isinstance(raw_hooks, list):
        return [_normalize_state_hook(item, index) for index, item in enumerate(raw_hooks, start=1)]
    return [_normalize_state_hook(raw_hooks, 1)]


def _normalize_state_hook(raw_hook: Any, index: int) -> dict[str, Any]:
    if isinstance(raw_hook, str):
        item: dict[str, Any] = {"name": raw_hook, "template": "statem_autoloop"}
    elif isinstance(raw_hook, dict):
        item = dict(raw_hook)
    else:
        raise StatemError(f"state hook {index} must be a mapping or string")

    event = item.get("event") or item.get("trigger") or item.get("on") or "stop"
    template = item.get("template") or item.get("type") or "statem_autoloop"
    name = item.get("name") or template
    scope = item.get("scope") or "current_entry"
    hosts = _normalize_state_hook_hosts(item.get("hosts", item.get("host", "any")))
    stop_states = item.get("stop_states", item.get("terminal_states"))
    if stop_states is None:
        normalized_stop_states = sorted(DEFAULT_STOP_STATES)
    elif isinstance(stop_states, str):
        normalized_stop_states = [part.strip() for part in stop_states.split(",") if part.strip()]
    elif isinstance(stop_states, list):
        normalized_stop_states = [str(part) for part in stop_states if str(part).strip()]
    else:
        raise StatemError(f"state hook {index} stop_states must be a list or comma-separated string")

    return {
        "name": str(name),
        "event": str(event),
        "template": str(template),
        "scope": str(scope),
        "hosts": hosts,
        "prompt": str(item.get("prompt") or item.get("text") or ""),
        "stop_states": normalized_stop_states,
    }


def _normalize_state_hook_hosts(raw_hosts: Any) -> list[str]:
    if raw_hosts is None or raw_hosts == "":
        return ["any"]
    if isinstance(raw_hosts, str):
        hosts = [part.strip() for part in raw_hosts.split(",") if part.strip()]
    elif isinstance(raw_hosts, list):
        hosts = [str(part).strip() for part in raw_hosts if str(part).strip()]
    else:
        raise StatemError("state hook host/hosts must be a string or list")
    return hosts or ["any"]


def _validate_state_hooks(raw_hooks: Any, label: str) -> list[str]:
    try:
        hooks = _normalize_state_hooks(raw_hooks)
    except StatemError as exc:
        return [f"{label}: {exc}"]
    errors: list[str] = []
    seen_names: set[str] = set()
    for hook in hooks:
        if not hook["name"].strip():
            errors.append(f"{label}: hook name cannot be empty")
        elif hook["name"] in seen_names:
            errors.append(f"{label}: duplicate hook name '{hook['name']}'")
        seen_names.add(hook["name"])
        if not hook["event"].strip():
            errors.append(f"{label}: hook event cannot be empty")
        if hook["template"] not in STATE_HOOK_TEMPLATES:
            errors.append(f"{label}: unsupported template '{hook['template']}'")
        if hook["scope"] != "current_entry":
            errors.append(f"{label}: only scope: current_entry is supported")
    return errors


def _normalize_dynamic_config(raw_config: Any) -> dict[str, Any]:
    if raw_config is None or raw_config == "":
        return {}
    if not isinstance(raw_config, dict):
        raise StatemError(f"{DYNAMIC_PURPOSE} must be a mapping")
    config = dict(raw_config)
    path = config.get("path", "current_entry")
    if path != "current_entry":
        raise StatemError(f"{DYNAMIC_PURPOSE} only supports path: current_entry")
    config["path"] = path
    config["required"] = bool(config.get("required", False))
    config["min_items"] = int(config.get("min_items") or 0)
    config["require_reason"] = bool(config.get("require_reason", False))
    config["require_basis"] = bool(config.get("require_basis", False))
    config["merge"] = str(config.get("merge") or "all")
    config["refresh"] = str(config.get("refresh") or "on_attempt")
    config["stale_policy"] = str(config.get("stale_policy") or "none")
    allow_types = config.get("allow_types")
    if allow_types is None:
        config["allow_types"] = sorted(CHECK_TYPES)
    elif isinstance(allow_types, list):
        config["allow_types"] = [str(item) for item in allow_types]
    else:
        raise StatemError(f"{DYNAMIC_PURPOSE} allow_types must be a list")
    return config


def _validate_dynamic_config(raw_config: Any, label: str) -> list[str]:
    try:
        config = _normalize_dynamic_config(raw_config)
    except (StatemError, ValueError) as exc:
        return [f"{label}: {exc}"]
    if not config:
        return []
    errors: list[str] = []
    unknown_types = sorted(set(config["allow_types"]) - CHECK_TYPES)
    if unknown_types:
        errors.append(f"{label}: allow_types includes unsupported type(s): {', '.join(unknown_types)}")
    if config["merge"] != "all":
        errors.append(f"{label}: only merge: all is supported")
    if config["refresh"] != "on_attempt":
        errors.append(f"{label}: only refresh: on_attempt is supported")
    if config["stale_policy"] not in {"none", "require_confirmation"}:
        errors.append(f"{label}: stale_policy must be 'none' or 'require_confirmation'")
    if config["min_items"] < 0:
        errors.append(f"{label}: min_items cannot be negative")
    return errors


def _dynamic_summary(raw_config: Any, path: Path | None) -> dict[str, Any] | None:
    config = _normalize_dynamic_config(raw_config)
    if not config:
        return None
    summary = {
        "path": config["path"],
        "required": config["required"],
        "min_items": config["min_items"],
        "require_reason": config["require_reason"],
        "require_basis": config["require_basis"],
        "allow_types": config["allow_types"],
        "merge": config["merge"],
        "refresh": config["refresh"],
        "stale_policy": config["stale_policy"],
    }
    if path is not None:
        summary["resolved_path"] = str(path)
    return summary


def _state_hook_summaries(raw_hooks: Any) -> list[dict[str, Any]]:
    return _normalize_state_hooks(raw_hooks)


def _state_hook_matches_host(hook: dict[str, Any], host: str) -> bool:
    host_name = str(host).strip()
    if not host_name:
        return True
    hosts = [str(item) for item in hook.get("hosts", [])]
    return "any" in hosts or host_name in hosts


def _load_dynamic_check_file(path: Path) -> Any:
    if not path.exists():
        raise StatemError(f"Dynamic checks file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text) if path.suffix.lower() == ".json" else miniyaml.loads(text)
    except Exception as exc:
        raise StatemError(f"Could not parse dynamic checks {path}: {exc}") from exc


def _checks_file_agent_id(path: Path) -> str:
    stem = path.stem
    prefix = "checks."
    return stem[len(prefix) :] if stem.startswith(prefix) else stem


def _dynamic_payload_producer(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("producer"), dict):
        return payload["producer"]
    return {}


def _dynamic_payload_checks(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("checks"), list):
        return payload["checks"]
    raise StatemError("Dynamic checks must be a list or a mapping with a checks list.\n" + DYNAMIC_CHECKS_SCHEMA_HINT)


def _normalize_dynamic_payload(payload: Any, agent_id: str, role: str) -> dict[str, Any]:
    checks = _dynamic_payload_checks(payload)
    if not agent_id:
        raise StatemError("Dynamic checks require an agent id. Pass --agent-id or set STATEM_AGENT_ID.")
    producer = _dynamic_payload_producer(payload)
    normalized = {
        "producer": {
            "agent_id": _clean_agent_id(str(agent_id or producer.get("agent_id") or "")),
            "role": str(role or producer.get("role") or ""),
        },
        "basis": payload.get("basis", {}) if isinstance(payload, dict) else {},
        "checks": checks,
    }
    if not normalized["producer"]["agent_id"]:
        raise StatemError("Dynamic checks require a non-empty producer.agent_id. Pass --agent-id or set STATEM_AGENT_ID.")
    return normalized


def _validate_dynamic_payload(payload: dict[str, Any], config: dict[str, Any], path: Path) -> None:
    problems: list[str] = []
    basis = payload.get("basis")
    if config.get("require_basis"):
        if not isinstance(basis, dict) or not str(basis.get("implementation_summary") or "").strip():
            problems.append(f"{path}: basis.implementation_summary is required")
    allowed = set(config.get("allow_types") or CHECK_TYPES)
    for index, raw_check in enumerate(payload.get("checks", []), start=1):
        if not isinstance(raw_check, dict):
            problems.append(f"{path}: check {index} must be a mapping")
            continue
        check = _normalize_item(raw_check, DYNAMIC_PURPOSE)
        if check["type"] not in allowed:
            problems.append(f"{path}: dynamic check {index} type '{check['type']}' is not allowed")
        if config.get("require_reason") and not str(raw_check.get("reason") or "").strip():
            problems.append(f"{path}: dynamic check {index} requires reason")
    if problems:
        allowed_text = ", ".join(sorted(allowed))
        raise StatemError(
            "; ".join(problems)
            + "\n"
            + f"Allowed dynamic check types for this state: {allowed_text}.\n"
            + _dynamic_checks_schema_hint(allowed)
        )


def _dynamic_checks_schema_hint(allowed_types: set[str] | None = None) -> str:
    allowed = set(allowed_types or CHECK_TYPES)
    examples = []
    if "manual" in allowed:
        examples.append("{'type': 'manual', 'prompt': 'Confirm ...', 'reason': '...'}")
    if "checklist" in allowed:
        examples.append("{'type': 'checklist', 'items': ['...'], 'reason': '...'}")
    if "predicate" in allowed:
        examples.append("{'type': 'predicate', 'path': '/app/file', 'exists': true, 'reason': '...'}")
    if "command" in allowed:
        examples.append("{'type': 'command', 'run': '...', 'reason': '...'}")
    if "llm_review" in allowed:
        examples.append("{'type': 'llm_review', 'prompt': 'Review ...', 'reason': '...'}")
    if "message" in allowed:
        examples.append("{'type': 'message', 'text': 'Prepare ...', 'reason': '...'}")
    return (
        "Accepted dynamic checks file shape: "
        "{'basis': {'implementation_summary': 'what changed and why these checks fit'}, "
        f"'checks': [{', '.join(examples)}]"
        "}. Pass --agent-id or set STATEM_AGENT_ID; producer metadata is owned by the CLI."
    )


def _summaries(raw_items: Any, purpose: str) -> list[dict[str, Any]]:
    return [_item_summary(item) for item in _normalize_items(raw_items, purpose)]


def _item_summary(item: dict[str, Any]) -> dict[str, Any]:
    item_type = item["type"]
    summary = {
        "type": item_type,
        "blocking": bool(item.get("blocking")),
        "on_failure": item.get("on_failure"),
    }
    if item_type == "command":
        summary["run"] = item.get("run")
    elif item_type == "llm_review":
        summary["run"] = item.get("run") or "$STATEM_LLM_REVIEW_CMD"
        summary["prompt"] = item.get("prompt") or item.get("text") or item.get("name")
        for key in ("accept_contains", "reject_contains", "accept_regex", "reject_regex"):
            if key in item:
                summary[key] = item[key]
    elif item_type == "predicate":
        summary["path"] = item.get("path")
        for key in ("exists", "non_empty", "contains", "not_contains", "matches", "json_path", "equals", "one_of"):
            if key in item:
                summary[key] = item[key]
    elif item_type == "checklist":
        summary["items"] = item.get("items") or item.get("checks")
    else:
        summary["text"] = item.get("prompt") or item.get("text") or item.get("name")
    return summary


def _edge_summary(edge: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "from": edge["from"],
        "to": edge["to"],
        "condition": _summaries(edge.get("condition"), "condition"),
        "hook": _summaries(edge.get("hook"), "hook"),
    }
    if "max_attempts" in edge:
        summary["max_attempts"] = edge["max_attempts"]
    return summary


def _hook_env(
    spec: StatemSpec,
    state: dict[str, Any],
    state_dir: Path,
    purpose: str,
    *,
    agent_id: str | None = None,
    agent_role: str | None = None,
) -> dict[str, str]:
    env = {
        **os.environ,
        "STATEM_RUN_ID": str(state.get("run_id", "")),
        "STATEM_SPEC": str(spec.path),
        "STATEM_STATE_DIR": str(state_dir),
        "STATEM_CURRENT": str(state.get("current", "")),
        "STATEM_ENTRY_ID": str(state.get("current_entry_id", "")),
        "STATEM_PURPOSE": purpose,
    }
    resolved_agent_id = _clean_agent_id(
        agent_id or os.environ.get("STATEM_AGENT_ID") or str(state.get("agent_id") or "")
    )
    resolved_agent_role = str(agent_role or os.environ.get("STATEM_AGENT_ROLE") or "").strip()
    if resolved_agent_id:
        env["STATEM_AGENT_ID"] = resolved_agent_id
    if resolved_agent_role:
        env["STATEM_AGENT_ROLE"] = resolved_agent_role
    return env


def _state_hook_autoloop_reason(
    hook: dict[str, Any],
    command: str,
    state_dir: Path,
    run_id: str,
    current: str,
    entry_id: str,
    next_edges: list[dict[str, Any]],
) -> str:
    next_names = ", ".join(str(edge.get("to")) for edge in next_edges if isinstance(edge, dict)) or "(none)"
    lines = [
        "Continue the active statem-managed run instead of stopping.",
        "",
        f"State hook: {hook.get('name')}",
        f"Current state: {current}",
        f"Current entry: {entry_id}",
        f"Allowed next states: {next_names}",
    ]
    if hook.get("prompt"):
        lines.extend(["", "State hook instruction:", str(hook["prompt"])])
    state_dir_arg = shlex.quote(str(state_dir))
    run_id_arg = shlex.quote(run_id)
    lines.extend(
        [
            "",
            "First inspect durable state:",
            f"{command} cur --run-id {run_id_arg} --state-dir {state_dir_arg} --json",
            f"{command} next --run-id {run_id_arg} --state-dir {state_dir_arg} --json",
            "",
            "Follow the current node prompt. Move only with `statem goto <next-state>`.",
            "If the current node requires user input or is ready for handoff, explain that and stop.",
        ]
    )
    return "\n".join(lines)


def _review_prompt(spec: StatemSpec, state: dict[str, Any], item: dict[str, Any], purpose: str) -> str:
    review_text = str(item.get("prompt") or item.get("text") or item.get("name") or "Review the current transition.")
    current = str(state.get("current", ""))
    parts = [
        review_text,
        "",
        "Statem context:",
        f"- run_id: {state.get('run_id', '')}",
        f"- spec: {spec.path}",
        f"- current: {current}",
        f"- purpose: {purpose}",
    ]
    if current in spec.nodes:
        prompt = spec.node_prompt(current)
        if prompt:
            parts.extend(["", "Current node prompt:", prompt])
    return "\n".join(parts).strip() + "\n"


def _result(
    item: dict[str, Any],
    purpose: str,
    passed: bool,
    *,
    output: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    blocking = bool(item.get("blocking"))
    on_failure = str(item.get("on_failure") or ("block" if blocking else "continue"))
    continued = not passed and on_failure == "continue"
    result = {
        "type": item["type"],
        "purpose": purpose,
        "passed": passed,
        "blocking": blocking,
        "on_failure": on_failure,
        "continued": continued,
        "output": output,
    }
    if exit_code is not None:
        result["exit_code"] = exit_code
    return result


def _has_blocking_failure(results: list[dict[str, Any]]) -> bool:
    return any(not result["passed"] and result.get("on_failure") == "block" for result in results)


def _raise_if_blocked(
    results: list[dict[str, Any]], message: str, *, details: dict[str, Any] | None = None
) -> None:
    if _has_blocking_failure(results):
        raise TransitionBlocked(message, details=details)


def _block_details(
    state: dict[str, Any], source: str, target: str, stage: str, results: list[dict[str, Any]]
) -> dict[str, Any]:
    blocking_results = [
        result for result in results if not result["passed"] and result.get("on_failure") == "block"
    ]
    pending_confirmation = [
        result
        for result in blocking_results
        if result.get("type") in {"manual", "checklist"} and "confirmation required" in str(result.get("output") or "")
    ]
    details = {
        "run_id": state["run_id"],
        "current": state["current"],
        "current_entry_id": state.get("current_entry_id"),
        "from": source,
        "to": target,
        "stage": stage,
        "results": results,
    }
    if pending_confirmation and len(pending_confirmation) == len(blocking_results):
        details["summary"] = (
            "All automatic checks passed; manual confirmation is pending. "
            "Rerun with --yes only after verifying the listed checklist/manual items."
        )
        details["pending_confirmation"] = [
            {"type": result.get("type"), "purpose": result.get("purpose"), "output": result.get("output")}
            for result in pending_confirmation
        ]
    elif pending_confirmation:
        details["summary"] = (
            "Some checklist/manual items still need confirmation, and at least one automatic check also failed."
        )
    return details


def _resolve_cwd(spec: StatemSpec, item: dict[str, Any]) -> Path:
    cwd_value = item.get("cwd")
    if cwd_value is None:
        return spec.path.parent
    path = Path(str(cwd_value)).expanduser()
    if not path.is_absolute():
        path = spec.path.parent / path
    return path.resolve()


def _resolve_path(spec: StatemSpec, item: dict[str, Any], path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (_resolve_cwd(spec, item) / path).resolve()


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8]


def _new_entry_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]


def _new_agent_id() -> str:
    return "agent-" + _new_entry_id()


def _clean_run_id(run_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(run_id).strip())
    if not cleaned:
        raise StatemError("run id cannot be empty")
    return cleaned


def _clean_agent_id(agent_id: str) -> str:
    if not agent_id:
        return ""
    raw = str(agent_id).strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)
    if cleaned == raw:
        return cleaned
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}-{digest}"


def _clean_node_id(node_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(node_name).strip())
    return cleaned or "node"
