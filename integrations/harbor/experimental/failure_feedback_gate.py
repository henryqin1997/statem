from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


DEFAULT_DECISION = Path("/tmp/statem-verification-checks/recovering-develop/replay-decision.json")
DEFAULT_BRIEF = Path("/tmp/statem-verification-checks/recovering-develop/retry-brief.json")
DEFAULT_PREFLIGHT = Path("/tmp/statem-verification-checks/multirole/preflight-evidence.json")
DEFAULT_VALIDATION = Path("/tmp/statem-verification-checks/recovering-develop/validation-delta-receipt.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carry a host-validated failure and validation delta into the next candidate-blind plan."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    prepare.add_argument("--output", type=Path, default=DEFAULT_BRIEF)
    validate = sub.add_parser("validate-preflight")
    validate.add_argument("--brief", type=Path, default=DEFAULT_BRIEF)
    validate.add_argument("--preflight-evidence", type=Path, default=DEFAULT_PREFLIGHT)
    validate.add_argument("--output", type=Path, default=DEFAULT_VALIDATION)
    args = parser.parse_args(argv)
    if args.action == "validate-preflight":
        # A failed validation must not leave an earlier cycle's success receipt
        # available to progress or audit consumers.
        args.output.unlink(missing_ok=True)
    try:
        if args.action == "prepare":
            receipt = prepare_retry_brief(
                _read_json(args.decision) if args.decision.is_file() else None
            )
        else:
            receipt = validate_preflight_delta(
                brief=_read_json(args.brief),
                preflight_evidence=_read_json(args.preflight_evidence),
            )
        _write_json(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"failure feedback gate: {exc}")
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def prepare_retry_brief(decision: dict[str, Any] | None) -> dict[str, Any]:
    if decision is None:
        return {
            "version": 1,
            "kind": "failure_feedback_retry_brief",
            "required": False,
            "reason": "initial_cycle",
            "failure_closure_sha256": "",
            "failure_ownership": None,
            "validation_delta": None,
            "created_at": _now(),
        }
    if (
        decision.get("version") != 1
        or decision.get("kind") != "recovering_develop_replay_decision"
    ):
        raise ValueError("expected a version-1 recovering_develop_replay_decision")
    required = decision.get("action") == "retry"
    ownership = decision.get("failure_ownership")
    delta = decision.get("validation_delta")
    if required and (not isinstance(ownership, dict) or not isinstance(delta, dict)):
        raise ValueError("retry decision is missing failure ownership or validation delta")
    return {
        "version": 1,
        "kind": "failure_feedback_retry_brief",
        "required": required,
        "reason": "authorized_retry" if required else "no_retry_authorized",
        "failure_closure_sha256": stable_sha256(decision) if required else "",
        "failure_ownership": ownership if required else None,
        "validation_delta": delta if required else None,
        "created_at": _now(),
    }


def validate_preflight_delta(
    *,
    brief: dict[str, Any],
    preflight_evidence: dict[str, Any],
) -> dict[str, Any]:
    if brief.get("version") != 1 or brief.get("kind") != "failure_feedback_retry_brief":
        raise ValueError("expected a version-1 failure_feedback_retry_brief")
    if (
        preflight_evidence.get("version") != 1
        or preflight_evidence.get("kind") != "plan_preflight_evidence"
    ):
        raise ValueError("expected a version-1 plan_preflight_evidence receipt")
    if not brief.get("required"):
        return {
            "version": 1,
            "kind": "validation_delta_application",
            "required": False,
            "applied": True,
            "reason": "initial_or_handoff_cycle",
            "failure_closure_sha256": "",
            "matched_requirement_ids": [],
            "preflight_evidence_sha256": stable_sha256(preflight_evidence),
            "created_at": _now(),
        }

    delta = brief.get("validation_delta")
    if not isinstance(delta, dict):
        raise ValueError("retry brief validation_delta is required")
    check = _text(delta.get("discriminating_check"))
    if not check:
        raise ValueError("retry validation delta requires a discriminating check")
    plan = preflight_evidence.get("acceptance_plan")
    requirements = plan.get("requirements") if isinstance(plan, dict) else None
    if not isinstance(requirements, list):
        raise ValueError("preflight evidence is missing candidate-blind requirements")
    matched: list[str] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        strata = item.get("required_strata")
        if isinstance(strata, list) and check in strata:
            matched.append(_text(item.get("requirement_id")))
    if not matched:
        raise ValueError(
            "candidate-blind acceptance plan did not append the exact prior validation delta"
        )
    return {
        "version": 1,
        "kind": "validation_delta_application",
        "required": True,
        "applied": True,
        "reason": "exact_discriminator_bound_to_candidate_blind_plan",
        "failure_closure_sha256": _text(brief.get("failure_closure_sha256")),
        "validation_delta_sha256": stable_sha256(delta),
        "matched_requirement_ids": matched,
        "preflight_evidence_sha256": stable_sha256(preflight_evidence),
        "created_at": _now(),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
