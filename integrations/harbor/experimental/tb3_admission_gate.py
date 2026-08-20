from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    from statem.miniyaml import loads as _yaml_loads
else:
    _yaml_loads = yaml.safe_load


REQUIRED_FIELDS = {
    "job_name",
    "task",
    "control_version",
    "experiment_mode",
    "platform_class",
    "dominant_limit_prior",
    "evidence_basis",
    "owning_control_layer",
    "hardware_feasibility",
    "required_cpus",
    "required_memory_mb",
    "required_gpus",
    "cheapest_public_discriminator",
    "expected_api_cost_usd",
    "expected_wall_time_seconds",
    "observable_progress_target",
    "stop_or_park_condition",
    "hypothesis_scoped_no_progress_count",
    "new_generic_hypothesis",
    "requested_decision",
}
DECISIONS = {"admit", "defer", "reject"}
LIMIT_CLASSES = {
    "statem_controllable_workflow",
    "base_model_capability",
    "hardware_or_resource",
    "mixed",
    "unresolved",
}


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _queue_tasks(value: Any) -> set[str]:
    tasks: set[str] = set()
    if isinstance(value, dict):
        task = value.get("task")
        if isinstance(task, str) and task.strip():
            tasks.add(task.strip())
        for child in value.values():
            tasks.update(_queue_tasks(child))
    elif isinstance(value, list):
        for child in value:
            tasks.update(_queue_tasks(child))
    return tasks


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def evaluate_admission(
    *,
    queue: dict[str, Any],
    queue_bytes: bytes,
    request: dict[str, Any],
    available_cpus: int,
    available_memory_mb: int,
    available_gpus: int,
    created_at_epoch: int | None = None,
) -> dict[str, Any]:
    missing = sorted(REQUIRED_FIELDS - set(request))
    extra = sorted(set(request) - REQUIRED_FIELDS)
    if missing or extra:
        raise ValueError(
            f"admission request fields mismatch: missing={missing}, extra={extra}"
        )
    for field in (
        "job_name",
        "task",
        "control_version",
        "experiment_mode",
        "platform_class",
        "evidence_basis",
        "owning_control_layer",
        "hardware_feasibility",
        "cheapest_public_discriminator",
        "observable_progress_target",
        "stop_or_park_condition",
    ):
        if not isinstance(request[field], str) or not request[field].strip():
            raise ValueError(f"admission request {field} must be a non-empty string")
    if request["dominant_limit_prior"] not in LIMIT_CLASSES:
        raise ValueError("admission request has an invalid dominant_limit_prior")
    if request["requested_decision"] not in DECISIONS:
        raise ValueError("admission request has an invalid requested_decision")
    if not isinstance(request["new_generic_hypothesis"], bool):
        raise ValueError("new_generic_hypothesis must be boolean")
    for field in (
        "required_cpus",
        "required_memory_mb",
        "required_gpus",
        "hypothesis_scoped_no_progress_count",
    ):
        if not _nonnegative_int(request[field]):
            raise ValueError(f"admission request {field} must be a non-negative integer")
    if request["required_cpus"] < 1 or request["required_memory_mb"] < 1:
        raise ValueError("admission request requires positive CPU and memory")
    for field in ("expected_api_cost_usd", "expected_wall_time_seconds"):
        if not _positive_number(request[field]):
            raise ValueError(f"admission request {field} must be positive")
    if min(available_cpus, available_memory_mb, available_gpus) < 0:
        raise ValueError("available resources must be non-negative")

    reasons: list[str] = []
    decision = "admit"
    task = request["task"].strip()
    if task not in _queue_tasks(queue):
        decision = "reject"
        reasons.append("task_not_in_bound_queue")

    hardware_unavailable = (
        request["required_cpus"] > available_cpus
        or request["required_memory_mb"] > available_memory_mb
        or request["required_gpus"] > available_gpus
        or request["hardware_feasibility"].strip().lower()
        in {"unavailable", "infeasible", "false"}
    )
    if hardware_unavailable:
        decision = "reject"
        reasons.append("hardware_requirement_unavailable")

    no_progress_limit = int(
        queue.get("triage_policy", {}).get("no_progress_limit", 2)
    )
    if (
        request["hypothesis_scoped_no_progress_count"] >= no_progress_limit
        and not request["new_generic_hypothesis"]
    ):
        decision = "reject"
        reasons.append("hypothesis_no_progress_limit_reached")

    discriminator = request["cheapest_public_discriminator"].strip().lower()
    no_discriminator = discriminator in {
        "none",
        "unavailable",
        "no_public_discriminator",
    } or discriminator.startswith("defer_")
    if decision != "reject" and no_discriminator:
        decision = "defer"
        reasons.append("no_current_public_discriminator")

    if (
        decision != "reject"
        and request["dominant_limit_prior"]
        in {"base_model_capability", "hardware_or_resource"}
        and not request["new_generic_hypothesis"]
    ):
        decision = "defer"
        reasons.append("dominant_limit_not_currently_statem_controllable")

    if not reasons:
        reasons.append("complete_low_risk_information_gain_case")
    requested_decision = request["requested_decision"]
    valid = requested_decision == decision
    payload = {
        "version": 2,
        "kind": "tb3_prelaunch_admission_receipt",
        "queue_sha256": hashlib.sha256(queue_bytes).hexdigest(),
        "request_sha256": stable_sha256(request),
        "job_name": request["job_name"],
        "task": task,
        "control_version": request["control_version"],
        "experiment_mode": request["experiment_mode"],
        "platform_class": request["platform_class"],
        "dominant_limit_prior": request["dominant_limit_prior"],
        "evidence_basis": request["evidence_basis"],
        "owning_control_layer": request["owning_control_layer"],
        "hardware_feasibility": request["hardware_feasibility"],
        "resources": {
            "required_cpus": request["required_cpus"],
            "required_memory_mb": request["required_memory_mb"],
            "required_gpus": request["required_gpus"],
            "available_cpus": available_cpus,
            "available_memory_mb": available_memory_mb,
            "available_gpus": available_gpus,
        },
        "cheapest_public_discriminator": request[
            "cheapest_public_discriminator"
        ],
        "expected_api_cost_usd": request["expected_api_cost_usd"],
        "expected_wall_time_seconds": request["expected_wall_time_seconds"],
        "observable_progress_target": request["observable_progress_target"],
        "stop_or_park_condition": request["stop_or_park_condition"],
        "hypothesis_scoped_no_progress_count": request[
            "hypothesis_scoped_no_progress_count"
        ],
        "new_generic_hypothesis": request["new_generic_hypothesis"],
        "requested_decision": requested_decision,
        "admission_decision": decision,
        "decision_reasons": sorted(set(reasons)),
        "valid": valid,
        "created_at_epoch": int(created_at_epoch or time.time()),
    }
    payload["receipt_sha256"] = stable_sha256(payload)
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    value = _yaml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("queue root must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("admission request root must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Host-side prelaunch admission gate for TB3 development cells."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--available-cpus", type=int, required=True)
    parser.add_argument("--available-memory-mb", type=int, required=True)
    parser.add_argument("--available-gpus", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    queue_bytes = args.queue.read_bytes()
    receipt = evaluate_admission(
        queue=_read_yaml(args.queue),
        queue_bytes=queue_bytes,
        request=_read_json(args.request),
        available_cpus=args.available_cpus,
        available_memory_mb=args.available_memory_mb,
        available_gpus=args.available_gpus,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    return 0 if receipt["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
