from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


PLAN_FIELDS = {"objective", "stages"}
STAGE_FIELDS = {
    "stage_id",
    "objective",
    "inputs",
    "outputs",
    "invariants",
    "acceptance_checks",
    "resource_budget",
    "dependencies",
    "risk",
    "challenger_budget",
}
RESOURCE_FIELDS = {"wall_seconds", "tool_calls"}
CANDIDATE_FIELDS = {
    "candidate_id",
    "stage_id",
    "producer_id",
    "artifact_identity",
    "snapshot_sha256",
    "mandatory_checks",
    "optional_checks",
    "resource_usage",
    "isolation",
}
CHECK_FIELDS = {"check_id", "status", "evidence"}
RANKING_FIELDS = {
    "stage_id",
    "plan_sha256",
    "reviewer_id",
    "candidate_order",
    "winner_id",
    "evidence",
    "unresolved",
}


def record_stage_plan(draft: dict[str, Any]) -> dict[str, Any]:
    if set(draft) != PLAN_FIELDS or not _text(draft.get("objective")):
        raise ValueError("stage portfolio plan requires exactly objective and stages")
    stages = draft.get("stages")
    if not isinstance(stages, list) or not 1 <= len(stages) <= 3:
        raise ValueError("stage portfolio requires one to three stages")
    normalized = [_stage(item) for item in stages]
    ids = [item["stage_id"] for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("stage ids must be unique")
    known: set[str] = set()
    for item in normalized:
        if any(dependency not in known for dependency in item["dependencies"]):
            raise ValueError("stage dependencies must reference earlier stages")
        known.add(item["stage_id"])
    plan = {
        "version": 1,
        "kind": "stage_portfolio_plan",
        "objective": _text(draft["objective"]),
        "stages": normalized,
        "max_stages": 3,
        "isolation_required": True,
        "lead_owns_integration": True,
        "final_promotion_requires_untouched_replay": True,
    }
    return {**plan, "plan_sha256": stable_sha256(plan)}


def screen_stage_candidates(
    *,
    plan: dict[str, Any],
    stage_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    _require_plan(plan)
    stage = _stage_by_id(plan, stage_id)
    if not 1 <= len(candidates) <= stage["challenger_budget"]:
        raise ValueError("candidate count exceeds the stage challenger budget")
    normalized = [_candidate(item, stage) for item in candidates]
    ids = [item["candidate_id"] for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("candidate ids must be unique within a stage")
    eligible: list[str] = []
    rejected: list[dict[str, Any]] = []
    for item in normalized:
        failed = [
            check["check_id"]
            for check in item["mandatory_checks"]
            if check["status"] != "passed"
        ]
        if failed:
            rejected.append({"candidate_id": item["candidate_id"], "failed_checks": failed})
        else:
            eligible.append(item["candidate_id"])
    receipt = {
        "version": 1,
        "kind": "stage_candidate_screen",
        "plan_sha256": plan["plan_sha256"],
        "stage_id": stage_id,
        "candidates": normalized,
        "eligible_candidate_ids": eligible,
        "rejected_candidates": rejected,
        "semantic_ranking_performed": False,
    }
    return {**receipt, "screen_sha256": stable_sha256(receipt)}


def authorize_stage_selection(
    *,
    plan: dict[str, Any],
    screen: dict[str, Any],
    ranking: dict[str, Any],
) -> dict[str, Any]:
    _require_plan(plan)
    if screen.get("version") != 1 or screen.get("kind") != "stage_candidate_screen":
        raise ValueError("selection requires a stage candidate screen")
    if screen.get("plan_sha256") != plan["plan_sha256"]:
        raise ValueError("candidate screen is not bound to the stage plan")
    if screen.get("screen_sha256") != stable_sha256(
        {key: value for key, value in screen.items() if key != "screen_sha256"}
    ):
        raise ValueError("candidate screen changed after deterministic screening")
    if set(ranking) != RANKING_FIELDS:
        raise ValueError("reviewer ranking has an invalid schema")
    if ranking.get("stage_id") != screen.get("stage_id"):
        raise ValueError("reviewer ranking targets another stage")
    if ranking.get("plan_sha256") != plan["plan_sha256"]:
        raise ValueError("reviewer ranking is not bound to the stage plan")
    if not _text(ranking.get("reviewer_id")) or not _string_list(ranking.get("evidence")):
        raise ValueError("reviewer identity and ranking evidence are required")
    eligible = list(screen.get("eligible_candidate_ids") or [])
    order = ranking.get("candidate_order")
    if not isinstance(order, list) or len(order) != len(eligible) or set(order) != set(eligible):
        raise ValueError("reviewer ranking must order exactly the eligible candidates")
    unresolved = ranking.get("unresolved")
    winner = _text(ranking.get("winner_id"))
    if not isinstance(unresolved, bool):
        raise ValueError("reviewer ranking unresolved must be boolean")
    if unresolved:
        if winner:
            raise ValueError("an unresolved ranking cannot select a winner")
    elif not order or winner != order[0]:
        raise ValueError("resolved ranking winner must be the first eligible candidate")
    receipt = {
        "version": 1,
        "kind": "stage_selection_authorization",
        "plan_sha256": plan["plan_sha256"],
        "screen_sha256": screen["screen_sha256"],
        "stage_id": screen["stage_id"],
        "reviewer_id": ranking["reviewer_id"],
        "winner_id": winner or None,
        "candidate_order": order,
        "evidence": list(ranking["evidence"]),
        "unresolved": unresolved,
        "lead_integration_authorized": not unresolved,
        "final_promotion_authority": False,
        "untouched_final_replay_required": True,
    }
    return {**receipt, "selection_sha256": stable_sha256(receipt)}


def _stage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != STAGE_FIELDS:
        raise ValueError("stage has an invalid schema")
    stage_id = _text(value.get("stage_id"))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", stage_id):
        raise ValueError("stage_id must be a short stable identifier")
    risk = value.get("risk")
    budget = value.get("challenger_budget")
    if risk not in {"low", "medium", "high"} or budget not in {1, 2}:
        raise ValueError("stage risk or challenger budget is invalid")
    if budget == 2 and risk != "high":
        raise ValueError("only a high-risk stage may use two challengers")
    resource = _resource(value.get("resource_budget"), "resource budget")
    fields = {
        name: _required_string_list(value.get(name), name)
        for name in ("inputs", "outputs", "invariants", "acceptance_checks")
    }
    dependencies = value.get("dependencies")
    if not isinstance(dependencies, list) or not all(_text(item) for item in dependencies):
        raise ValueError("stage dependencies must be a string list")
    return {
        "stage_id": stage_id,
        "objective": _required_text(value.get("objective"), "stage objective"),
        **fields,
        "resource_budget": resource,
        "dependencies": list(dependencies),
        "risk": risk,
        "challenger_budget": budget,
    }


def _candidate(value: Any, stage: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CANDIDATE_FIELDS:
        raise ValueError("stage candidate has an invalid schema")
    if value.get("stage_id") != stage["stage_id"]:
        raise ValueError("stage candidate targets another stage")
    if value.get("isolation") != "isolated_snapshot":
        raise ValueError("stage candidates require isolated snapshots")
    for field in ("candidate_id", "producer_id", "artifact_identity", "snapshot_sha256"):
        _required_text(value.get(field), field)
    usage = _resource(value.get("resource_usage"), "resource usage", allow_zero=True)
    for field in RESOURCE_FIELDS:
        if usage[field] > stage["resource_budget"][field]:
            raise ValueError("stage candidate exceeded its resource budget")
    mandatory = _checks(value.get("mandatory_checks"))
    expected = stage["acceptance_checks"]
    if [item["check_id"] for item in mandatory] != expected:
        raise ValueError("mandatory checks must exactly match stage acceptance checks")
    optional = _checks(value.get("optional_checks"), allow_empty=True)
    return {
        "candidate_id": _text(value["candidate_id"]),
        "stage_id": stage["stage_id"],
        "producer_id": _text(value["producer_id"]),
        "artifact_identity": _text(value["artifact_identity"]),
        "snapshot_sha256": _text(value["snapshot_sha256"]),
        "mandatory_checks": mandatory,
        "optional_checks": optional,
        "resource_usage": usage,
        "isolation": "isolated_snapshot",
    }


def _checks(value: Any, *, allow_empty: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError("candidate checks must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != CHECK_FIELDS:
            raise ValueError("candidate check has an invalid schema")
        check_id = _required_text(item.get("check_id"), "check_id")
        status = item.get("status")
        evidence = _required_text(item.get("evidence"), "check evidence")
        if check_id in seen or status not in {"passed", "failed", "unresolved"}:
            raise ValueError("candidate check is duplicated or has an invalid status")
        seen.add(check_id)
        normalized.append({"check_id": check_id, "status": status, "evidence": evidence})
    return normalized


def _resource(value: Any, label: str, *, allow_zero: bool = False) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != RESOURCE_FIELDS:
        raise ValueError(f"{label} has an invalid schema")
    minimum = 0 if allow_zero else 1
    if any(not isinstance(value[field], int) or value[field] < minimum for field in RESOURCE_FIELDS):
        raise ValueError(f"{label} values are invalid")
    return {field: value[field] for field in RESOURCE_FIELDS}


def _require_plan(plan: dict[str, Any]) -> None:
    if plan.get("version") != 1 or plan.get("kind") != "stage_portfolio_plan":
        raise ValueError("expected a version-1 stage portfolio plan")
    expected = stable_sha256({key: value for key, value in plan.items() if key != "plan_sha256"})
    if plan.get("plan_sha256") != expected:
        raise ValueError("stage portfolio plan changed after validation")


def _stage_by_id(plan: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in plan["stages"]:
        if stage["stage_id"] == stage_id:
            return stage
    raise ValueError(f"unknown stage: {stage_id}")


def _required_string_list(value: Any, field: str) -> list[str]:
    if not _string_list(value):
        raise ValueError(f"{field} must be a non-empty string list")
    return [_text(item) for item in value]


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _required_text(value: Any, field: str) -> str:
    text = _text(value)
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a bounded stage portfolio.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--draft", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    screen = subparsers.add_parser("screen")
    screen.add_argument("--plan", type=Path, required=True)
    screen.add_argument("--stage-id", required=True)
    screen.add_argument("--candidates", type=Path, required=True)
    screen.add_argument("--output", type=Path, required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--plan", type=Path, required=True)
    select.add_argument("--screen", type=Path, required=True)
    select.add_argument("--ranking", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "plan":
            receipt = record_stage_plan(_read_json(args.draft))
        elif args.action == "screen":
            candidates = _read_json(args.candidates)
            if not isinstance(candidates, list):
                raise ValueError("candidates JSON must be a list")
            receipt = screen_stage_candidates(
                plan=_read_json(args.plan),
                stage_id=args.stage_id,
                candidates=candidates,
            )
        else:
            receipt = authorize_stage_selection(
                plan=_read_json(args.plan),
                screen=_read_json(args.screen),
                ranking=_read_json(args.ranking),
            )
        _write_json(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"stage portfolio v2: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
