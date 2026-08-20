from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import file_sha256, stable_sha256
except ImportError:
    from artifact_identity import file_sha256, stable_sha256  # type: ignore[no-redef]


DEFAULT_DIR = Path("/tmp/statem-verification-checks/activation")
DEFAULT_DRAFT = DEFAULT_DIR / "activation-draft.json"
DEFAULT_TASK = Path("/tmp/statem-verification-checks/task.txt")
DEFAULT_SEAL = Path("/tmp/statem-verification-checks/multirole/contract-seal.json")
DEFAULT_OUTPUT = DEFAULT_DIR / "activation-receipt.json"
ROUTES = {"direct_solve", "evidence_develop"}
RISK_LEVELS = {"low", "medium", "high"}
DRAFT_FIELDS = {
    "recommended_route",
    "contract_ambiguity",
    "mutation_risk",
    "state_or_resource_risk",
    "quantitative_acceptance",
    "public_checks_available",
    "semantic_forks",
    "reasons",
}
MAX_LIST_ITEMS = 8
MAX_TEXT_CHARS = 600


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Conservatively classify whether evidence-develop controls should activate."
    )
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--task", type=Path, default=DEFAULT_TASK)
    parser.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    parser.add_argument("--mode", choices=("shadow", "enforce"), default="shadow")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        receipt = decide_activation(
            draft=_read_json(args.draft),
            task_path=args.task,
            seal=_read_json(args.seal),
            mode=args.mode,
        )
        _write_json(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"develop activation gate: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def decide_activation(
    *,
    draft: dict[str, Any],
    task_path: Path,
    seal: dict[str, Any],
    mode: str = "shadow",
) -> dict[str, Any]:
    if mode not in {"shadow", "enforce"}:
        raise ValueError("activation mode must be shadow or enforce")
    _require_receipt(seal, "contract_seal")
    context = _state_context()
    if context["node"] != "contract_audit":
        raise ValueError("develop activation belongs to contract_audit")
    if seal.get("run_id") != context["run_id"]:
        raise ValueError("contract seal belongs to another StateM run")
    normalized = _normalize_draft(draft)
    task_path = task_path.expanduser().resolve()
    if not task_path.is_file():
        raise ValueError("task-visible source is missing")

    reason_codes: list[str] = []
    for field in ("contract_ambiguity", "mutation_risk", "state_or_resource_risk"):
        if normalized[field] != "low":
            reason_codes.append(f"{field}:{normalized[field]}")
    if normalized["quantitative_acceptance"]:
        reason_codes.append("quantitative_acceptance")
    if not normalized["public_checks_available"]:
        reason_codes.append("public_checks_unavailable")
    if normalized["semantic_forks"]:
        reason_codes.append("semantic_forks_present")
    if normalized["recommended_route"] == "evidence_develop":
        reason_codes.append("model_requested_evidence_develop")

    direct_eligible = not reason_codes
    host_route = "direct_solve" if direct_eligible else "evidence_develop"
    effective_route = host_route if mode == "enforce" else "evidence_develop"
    return {
        "version": 1,
        "kind": "develop_activation_decision",
        **context,
        "producer": {
            "agent_id": f"activation-gate:{context['run_id']}:{context['entry_id']}",
            "role": "deterministic_gate",
        },
        "mode": mode,
        "task_sha256": file_sha256(task_path),
        "contract_seal_sha256": stable_sha256(seal),
        "draft_sha256": stable_sha256(draft),
        "classification": normalized,
        "direct_eligible": direct_eligible,
        "host_route": host_route,
        "effective_route": effective_route,
        "reason_codes": sorted(set(reason_codes)),
        "created_at": _now(),
    }


def _normalize_draft(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != DRAFT_FIELDS:
        raise ValueError(
            "activation draft requires exactly " + ", ".join(sorted(DRAFT_FIELDS))
        )
    recommended_route = _text(value.get("recommended_route"))
    if recommended_route not in ROUTES:
        raise ValueError("activation recommended_route is invalid")
    normalized: dict[str, Any] = {"recommended_route": recommended_route}
    for field in ("contract_ambiguity", "mutation_risk", "state_or_resource_risk"):
        risk = _text(value.get(field))
        if risk not in RISK_LEVELS:
            raise ValueError(f"activation {field} is invalid")
        normalized[field] = risk
    for field in ("quantitative_acceptance", "public_checks_available"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"activation {field} must be boolean")
        normalized[field] = value[field]
    for field in ("semantic_forks", "reasons"):
        items = value.get(field)
        if (
            not isinstance(items, list)
            or (field == "reasons" and not items)
            or len(items) > MAX_LIST_ITEMS
            or not all(_bounded_text(item) for item in items)
        ):
            raise ValueError(f"activation {field} is not a bounded string list")
        normalized[field] = [_bounded_text(item) for item in items]
    return normalized


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


def _bounded_text(value: Any) -> str:
    text = _text(value)
    return text if 0 < len(text) <= MAX_TEXT_CHARS else ""


def _require_receipt(receipt: dict[str, Any], kind: str) -> None:
    if receipt.get("version") != 1 or receipt.get("kind") != kind:
        raise ValueError(f"expected version-1 {kind} receipt")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
