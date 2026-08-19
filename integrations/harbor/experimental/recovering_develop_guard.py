from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import artifact_identity, stable_sha256
except ImportError:
    from artifact_identity import artifact_identity, stable_sha256  # type: ignore[no-redef]


DEFAULT_DIR = Path("/tmp/statem-verification-checks/recovering-develop")
DEFAULT_LEDGER = DEFAULT_DIR / "cycle-ledger.json"
DEFAULT_REPLAY_DRAFT = DEFAULT_DIR / "replay-draft.json"
DEFAULT_REPLAY_DECISION = DEFAULT_DIR / "replay-decision.json"
DEFAULT_PROMOTION_DECISION = Path(
    "/tmp/statem-verification-checks/multirole/promotion-decision.json"
)
DEFAULT_REVIEW_ROUTE = DEFAULT_DIR / "review-route.json"
DEFAULT_APPLICATION = Path(
    "/tmp/statem-verification-checks/multirole/application-receipt.json"
)
DEFAULT_SEAL = Path("/tmp/statem-verification-checks/multirole/contract-seal.json")
REPLAY_STATUSES = {"passed", "recoverable_failure", "terminal_failure"}
REVIEW_ROUTES = {"promote", "revise", "quarantine", "rollback"}
HARD_GAP_FIELDS = {
    "kind",
    "claim",
    "contract_basis",
    "evidence_status",
    "evidence_role",
    "population_access",
    "population_id",
    "observed_evidence",
    "required_evidence",
    "repair_action",
}
HARD_GAP_RESOLUTION_FIELDS = {"gap_sha256", "status", "evidence"}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "open":
            receipt = open_cycle(
                ledger_path=args.ledger,
                seal=_read_json(args.seal),
                max_cycles=args.max_cycles,
                max_reviews=args.max_reviews,
            )
        elif args.action == "review-open":
            receipt = open_review(ledger_path=args.ledger)
        elif args.action == "review-route":
            receipt = route_review(
                ledger_path=args.ledger,
                promotion_decision=_read_json(args.promotion_decision),
            )
            _write_json(args.output, receipt)
        elif args.action == "close":
            receipt = close_cycle(
                ledger_path=args.ledger,
                replay_draft=_read_json(args.replay_draft),
                application=_read_json(args.application),
                artifact_root=args.artifact_root,
            )
            _write_json(args.output, receipt)
        elif args.action == "require":
            receipt = _read_json(args.decision)
            require_action(receipt, set(args.allow))
        elif args.action == "require-review":
            receipt = _read_json(args.decision)
            require_review_route(receipt, set(args.allow))
        else:
            parser.error(f"unknown action: {args.action}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"recovering develop guard: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bound recovery cycles around the role-separated develop protocol."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    open_parser.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    open_parser.add_argument(
        "--max-cycles",
        type=int,
        default=_env_int("STATEM_DEVELOP_MAX_CYCLES", 2),
    )
    open_parser.add_argument(
        "--max-reviews",
        type=int,
        default=_env_int("STATEM_DEVELOP_MAX_REVIEWS", 2),
    )

    review_open = subparsers.add_parser("review-open")
    review_open.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    review_route = subparsers.add_parser("review-route")
    review_route.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    review_route.add_argument(
        "--promotion-decision", type=Path, default=DEFAULT_PROMOTION_DECISION
    )
    review_route.add_argument("--output", type=Path, default=DEFAULT_REVIEW_ROUTE)

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    close_parser.add_argument("--replay-draft", type=Path, default=DEFAULT_REPLAY_DRAFT)
    close_parser.add_argument("--application", type=Path, default=DEFAULT_APPLICATION)
    close_parser.add_argument("--artifact-root", type=Path, default=Path("/app"))
    close_parser.add_argument("--output", type=Path, default=DEFAULT_REPLAY_DECISION)

    require_parser = subparsers.add_parser("require")
    require_parser.add_argument("--decision", type=Path, default=DEFAULT_REPLAY_DECISION)
    require_parser.add_argument(
        "--allow",
        action="append",
        choices=("retry", "handoff"),
        required=True,
    )

    require_review = subparsers.add_parser("require-review")
    require_review.add_argument("--decision", type=Path, default=DEFAULT_REVIEW_ROUTE)
    require_review.add_argument(
        "--allow",
        action="append",
        choices=tuple(sorted(REVIEW_ROUTES)),
        required=True,
    )
    return parser


def open_cycle(
    *,
    ledger_path: Path,
    seal: dict[str, Any],
    max_cycles: int,
    max_reviews: int = 2,
) -> dict[str, Any]:
    _require_receipt(seal, "contract_seal")
    context = _state_context()
    if context["node"] != "contract_audit":
        raise ValueError("a recovery cycle can only open in contract_audit")
    if max_cycles < 1:
        raise ValueError("max_cycles must be positive")
    if max_reviews < 1:
        raise ValueError("max_reviews must be positive")
    if ledger_path.exists():
        ledger = _read_json(ledger_path)
        _validate_ledger(ledger)
        if ledger["max_cycles"] != max_cycles:
            raise ValueError("max_cycles cannot change after the first cycle")
        if ledger.get("max_reviews") != max_reviews:
            raise ValueError("max_reviews cannot change after the first cycle")
    else:
        ledger = {
            "version": 1,
            "kind": "recovering_develop_cycle_ledger",
            "run_id": context["run_id"],
            "max_cycles": max_cycles,
            "max_reviews": max_reviews,
            "cycles": [],
        }
    if ledger["run_id"] != context["run_id"]:
        raise ValueError("cycle ledger belongs to another StateM run")
    if ledger["cycles"] and ledger["cycles"][-1]["status"] == "open":
        raise ValueError("the previous recovery cycle is still open")
    if len(ledger["cycles"]) >= max_cycles:
        raise ValueError(f"recovery cycle budget exhausted at {max_cycles}")

    cycle = {
        "index": len(ledger["cycles"]) + 1,
        "status": "open",
        "contract_entry_id": context["entry_id"],
        "contract_seal_sha256": stable_sha256(seal),
        "baseline_artifact_identity": seal["baseline_artifact_identity"],
        "opened_at": _now(),
        "reviews": [],
    }
    ledger["cycles"].append(cycle)
    _write_json(ledger_path, ledger)
    return {
        "version": 1,
        "kind": "recovering_develop_cycle_opened",
        **context,
        "cycle": cycle["index"],
        "remaining_after_current": max_cycles - cycle["index"],
        "baseline_artifact_identity": cycle["baseline_artifact_identity"],
        "ledger_sha256": stable_sha256(ledger),
    }


def open_review(*, ledger_path: Path) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    _validate_ledger(ledger)
    context = _state_context()
    if context["node"] != "falsify":
        raise ValueError("a review can only open in falsify")
    if ledger["run_id"] != context["run_id"]:
        raise ValueError("cycle ledger belongs to another StateM run")
    if not ledger["cycles"] or ledger["cycles"][-1]["status"] != "open":
        raise ValueError("there is no open recovery cycle")
    cycle = ledger["cycles"][-1]
    reviews = cycle.setdefault("reviews", [])
    if len(reviews) >= ledger["max_reviews"]:
        raise ValueError("review budget exhausted")
    review = {
        "index": len(reviews) + 1,
        "entry_id": context["entry_id"],
        "status": "open",
        "opened_at": _now(),
    }
    reviews.append(review)
    _write_json(ledger_path, ledger)
    return {
        "version": 1,
        "kind": "recovering_develop_review_opened",
        **context,
        "cycle": cycle["index"],
        "review": review["index"],
        "remaining_reviews": ledger["max_reviews"] - len(reviews),
        "ledger_sha256": stable_sha256(ledger),
    }


def route_review(
    *,
    ledger_path: Path,
    promotion_decision: dict[str, Any],
) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    _validate_ledger(ledger)
    _require_receipt(promotion_decision, "promotion_authorization")
    context = _state_context()
    if context["node"] != "falsify":
        raise ValueError("a review can only route in falsify")
    if ledger["run_id"] != context["run_id"]:
        raise ValueError("cycle ledger belongs to another StateM run")
    cycle = ledger["cycles"][-1]
    reviews = cycle.get("reviews") or []
    if not reviews:
        raise ValueError("there is no open review")
    review = reviews[-1]
    if review.get("entry_id") != context["entry_id"]:
        raise ValueError("promotion decision belongs to another review entry")

    decision = promotion_decision.get("decision")
    if decision not in {"promote", "revise", "rollback"}:
        raise ValueError("promotion decision cannot be routed")
    decision_sha256 = stable_sha256(promotion_decision)
    if review.get("status") != "open":
        if review.get("promotion_decision_sha256") != decision_sha256:
            raise ValueError("review was already routed with another promotion decision")
        route = review.get("status")
        if route not in REVIEW_ROUTES:
            raise ValueError("review has an invalid routed status")
        return _review_route_receipt(
            ledger=ledger,
            cycle=cycle,
            review=review,
            context=context,
            promotion_decision=decision,
            promotion_decision_sha256=decision_sha256,
        )

    repairable_rejection = _repairable_rejection(promotion_decision)
    hard_contract_gaps = _validated_hard_contract_gaps(promotion_decision)
    route = "revise" if repairable_rejection else decision
    budget_exhausted = False
    if route == "revise" and len(reviews) >= ledger["max_reviews"]:
        route = "quarantine"
        budget_exhausted = True
    review["status"] = route
    review["promotion_decision_sha256"] = decision_sha256
    review["repairable_rejection"] = repairable_rejection
    review["budget_exhausted"] = budget_exhausted
    review["requires_recovery_cycle"] = bool(hard_contract_gaps)
    review["hard_contract_gaps"] = hard_contract_gaps
    review["artifact_disposition"] = {
        "promote": "candidate_active",
        "revise": "candidate_live",
        "quarantine": "candidate_quarantined",
        "rollback": "baseline_restore",
    }[route]
    review["evaluation_target"] = {
        "promote": "candidate",
        "revise": "none",
        "quarantine": "candidate",
        "rollback": "baseline",
    }[route]
    review["closed_at"] = _now()
    _write_json(ledger_path, ledger)
    return _review_route_receipt(
        ledger=ledger,
        cycle=cycle,
        review=review,
        context=context,
        promotion_decision=decision,
        promotion_decision_sha256=decision_sha256,
    )


def _review_route_receipt(
    *,
    ledger: dict[str, Any],
    cycle: dict[str, Any],
    review: dict[str, Any],
    context: dict[str, Any],
    promotion_decision: str,
    promotion_decision_sha256: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "recovering_develop_review_route",
        **context,
        "cycle": cycle["index"],
        "review": review["index"],
        "promotion_decision": promotion_decision,
        "promotion_decision_sha256": promotion_decision_sha256,
        "route": review["status"],
        "repairable_rejection": bool(review.get("repairable_rejection")),
        "review_budget_exhausted": bool(review.get("budget_exhausted")),
        "artifact_disposition": review.get("artifact_disposition"),
        "evaluation_target": review.get("evaluation_target"),
        "requires_recovery_cycle": bool(review.get("requires_recovery_cycle")),
        "hard_contract_gap_sha256s": [
            stable_sha256(item) for item in review.get("hard_contract_gaps") or []
        ],
        "remaining_reviews": ledger["max_reviews"] - len(cycle.get("reviews") or []),
        "ledger_sha256": stable_sha256(ledger),
    }


def _repairable_rejection(decision: dict[str, Any]) -> bool:
    if decision.get("decision") != "rollback":
        return False
    reason_codes = decision.get("reason_codes")
    checks = decision.get("checks")
    if not isinstance(reason_codes, list) or not isinstance(checks, dict):
        return False
    reasons = {str(item) for item in reason_codes}
    return (
        "validated_blocking_regression" in reasons
        and checks.get("contract_sources_unchanged") is True
        and checks.get("public_contract_unchanged") is True
    )


def _validated_hard_contract_gaps(decision: dict[str, Any]) -> list[dict[str, Any]]:
    reasons = decision.get("reason_codes")
    gaps = decision.get("hard_contract_gaps")
    declared = isinstance(reasons, list) and "validated_hard_contract_gap" in reasons
    if not declared:
        return []
    if not isinstance(gaps, list) or not gaps:
        raise ValueError("validated hard contract gap is missing structured evidence")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in gaps:
        if (
            not isinstance(item, dict)
            or set(item) != HARD_GAP_FIELDS
            or any(not str(item.get(field) or "").strip() for field in HARD_GAP_FIELDS)
        ):
            raise ValueError("hard contract gap has an invalid schema")
        identity = stable_sha256(item)
        if identity in seen:
            raise ValueError("hard contract gaps must be unique")
        seen.add(identity)
        normalized.append(dict(item))
    return normalized


def close_cycle(
    *,
    ledger_path: Path,
    replay_draft: dict[str, Any],
    application: dict[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    _validate_ledger(ledger)
    _require_receipt(application, "artifact_application_verification")
    context = _state_context()
    if context["node"] != "final_replay":
        raise ValueError("a recovery cycle can only close in final_replay")
    if ledger["run_id"] != context["run_id"]:
        raise ValueError("cycle ledger belongs to another StateM run")
    _validate_replay_draft(replay_draft)

    observed = artifact_identity(artifact_root)
    if not application.get("verified"):
        raise ValueError("artifact application receipt is not verified")
    if application.get("observed_artifact_identity") != observed:
        raise ValueError("replay artifact changed after application verification")

    if not ledger["cycles"]:
        raise ValueError("there is no open recovery cycle")
    cycle = ledger["cycles"][-1]
    replay_draft_sha256 = stable_sha256(replay_draft)
    application_sha256 = _semantic_receipt_sha256(application)
    if cycle["status"] != "open":
        bindings = {
            "replay_entry_id": context["entry_id"],
            "replay_draft_sha256": replay_draft_sha256,
            "application_sha256": application_sha256,
            "selected_artifact_identity": observed,
        }
        if any(cycle.get(field) != value for field, value in bindings.items()):
            raise ValueError(
                "recovery cycle was already closed with different replay evidence"
            )
        return _replay_decision_receipt(
            ledger=ledger,
            cycle=cycle,
            context=context,
        )

    hard_contract_gaps = _latest_hard_contract_gaps(cycle)
    unresolved_gap_sha256s = _unresolved_hard_gap_sha256s(
        hard_contract_gaps,
        replay_draft.get("hard_gap_resolutions") or [],
    )
    reported_status = replay_draft["status"]
    effective_status = reported_status
    next_gap = replay_draft["next_gap"]
    if unresolved_gap_sha256s and reported_status == "passed":
        effective_status = "recoverable_failure"
        unresolved = next(
            item
            for item in hard_contract_gaps
            if stable_sha256(item) == unresolved_gap_sha256s[0]
        )
        next_gap = str(unresolved["repair_action"]).strip()

    cycle["status"] = effective_status
    cycle["reported_status"] = reported_status
    cycle["replay_entry_id"] = context["entry_id"]
    cycle["replay_draft_sha256"] = replay_draft_sha256
    cycle["application_sha256"] = application_sha256
    cycle["selected_artifact_identity"] = observed
    cycle["evidence"] = list(replay_draft["evidence"])
    cycle["residual_risk"] = list(replay_draft["residual_risk"])
    cycle["next_gap"] = next_gap
    cycle["hard_gap_resolutions"] = list(replay_draft.get("hard_gap_resolutions") or [])
    cycle["unresolved_hard_gap_sha256s"] = unresolved_gap_sha256s
    cycle["closed_at"] = _now()

    can_retry = (
        effective_status == "recoverable_failure"
        and len(ledger["cycles"]) < ledger["max_cycles"]
    )
    action = "retry" if can_retry else "handoff"
    cycle["action"] = action
    if effective_status == "recoverable_failure" and not can_retry:
        cycle["residual_risk"].append("recovery cycle budget exhausted")
    _write_json(ledger_path, ledger)
    return _replay_decision_receipt(
        ledger=ledger,
        cycle=cycle,
        context=context,
    )


def _replay_decision_receipt(
    *,
    ledger: dict[str, Any],
    cycle: dict[str, Any],
    context: dict[str, str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "recovering_develop_replay_decision",
        **context,
        "cycle": cycle["index"],
        "status": cycle["status"],
        "reported_status": cycle.get("reported_status", cycle["status"]),
        "action": cycle["action"],
        "replay_draft_sha256": cycle["replay_draft_sha256"],
        "application_sha256": cycle["application_sha256"],
        "selected_artifact_identity": cycle["selected_artifact_identity"],
        "unresolved_hard_gap_sha256s": cycle.get(
            "unresolved_hard_gap_sha256s", []
        ),
        "remaining_cycles": ledger["max_cycles"] - len(ledger["cycles"]),
        "ledger_sha256": stable_sha256(ledger),
    }


def _semantic_receipt_sha256(receipt: dict[str, Any]) -> str:
    return stable_sha256(
        {key: value for key, value in receipt.items() if key != "created_at"}
    )


def require_action(decision: dict[str, Any], allowed: set[str]) -> None:
    _require_receipt(decision, "recovering_develop_replay_decision")
    if decision.get("action") not in allowed:
        raise ValueError(
            f"replay action {decision.get('action')!r} is not allowed here; expected {sorted(allowed)}"
        )


def require_review_route(decision: dict[str, Any], allowed: set[str]) -> None:
    _require_receipt(decision, "recovering_develop_review_route")
    if decision.get("route") not in allowed:
        raise ValueError(
            f"review route {decision.get('route')!r} is not allowed here; expected {sorted(allowed)}"
        )


def _validate_ledger(ledger: dict[str, Any]) -> None:
    if ledger.get("version") != 1 or ledger.get("kind") != "recovering_develop_cycle_ledger":
        raise ValueError("invalid recovery cycle ledger")
    if not _text(ledger.get("run_id")):
        raise ValueError("cycle ledger run_id is required")
    if not isinstance(ledger.get("max_cycles"), int) or ledger["max_cycles"] < 1:
        raise ValueError("cycle ledger max_cycles must be positive")
    if not isinstance(ledger.get("max_reviews"), int) or ledger["max_reviews"] < 1:
        raise ValueError("cycle ledger max_reviews must be positive")
    cycles = ledger.get("cycles")
    if not isinstance(cycles, list):
        raise ValueError("cycle ledger cycles must be a list")
    if len(cycles) > ledger["max_cycles"]:
        raise ValueError("cycle ledger exceeds max_cycles")
    for index, cycle in enumerate(cycles, start=1):
        if not isinstance(cycle, dict) or cycle.get("index") != index:
            raise ValueError("cycle ledger indices must be contiguous")
        if cycle.get("status") not in {"open", *REPLAY_STATUSES}:
            raise ValueError(f"cycle {index} has invalid status")
        if not _text(cycle.get("contract_entry_id")):
            raise ValueError(f"cycle {index} contract_entry_id is required")
        if not _text(cycle.get("baseline_artifact_identity")):
            raise ValueError(f"cycle {index} baseline identity is required")
        reviews = cycle.get("reviews")
        if not isinstance(reviews, list) or len(reviews) > ledger["max_reviews"]:
            raise ValueError(f"cycle {index} has invalid reviews")
        for review_index, review in enumerate(reviews, start=1):
            if not isinstance(review, dict) or review.get("index") != review_index:
                raise ValueError(f"cycle {index} review indices must be contiguous")
            if review.get("status") not in {"open", *REVIEW_ROUTES}:
                raise ValueError(f"cycle {index} review {review_index} has invalid status")


def _validate_replay_draft(draft: dict[str, Any]) -> None:
    required = {"status", "evidence", "residual_risk", "next_gap"}
    allowed = required | {"hard_gap_resolutions"}
    missing = sorted(required - set(draft))
    unknown = sorted(set(draft) - allowed)
    if missing:
        raise ValueError("replay draft is missing: " + ", ".join(missing))
    if unknown:
        raise ValueError("replay draft has unknown fields: " + ", ".join(unknown))
    if draft.get("status") not in REPLAY_STATUSES:
        raise ValueError("replay draft status is invalid")
    if not _string_list(draft.get("evidence")):
        raise ValueError("replay draft evidence must be a non-empty string list")
    if not isinstance(draft.get("residual_risk"), list) or not all(
        _text(item) for item in draft["residual_risk"]
    ):
        raise ValueError("replay draft residual_risk must be a string list")
    next_gap = _text(draft.get("next_gap"))
    if draft["status"] == "recoverable_failure" and not next_gap:
        raise ValueError("recoverable_failure requires a concrete next_gap")
    if draft["status"] != "recoverable_failure" and next_gap:
        raise ValueError("next_gap is only valid for recoverable_failure")
    resolutions = draft.get("hard_gap_resolutions") or []
    if not isinstance(resolutions, list):
        raise ValueError("hard_gap_resolutions must be a list")
    seen: set[str] = set()
    for item in resolutions:
        if not isinstance(item, dict) or set(item) != HARD_GAP_RESOLUTION_FIELDS:
            raise ValueError("hard gap resolution has an invalid schema")
        gap_sha256 = _text(item.get("gap_sha256"))
        if (
            not re.fullmatch(r"[0-9a-f]{64}", gap_sha256)
            or gap_sha256 in seen
            or item.get("status") not in {"resolved", "unresolved"}
            or not _text(item.get("evidence"))
        ):
            raise ValueError("hard gap resolution is incomplete or duplicated")
        seen.add(gap_sha256)


def _latest_hard_contract_gaps(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = cycle.get("reviews") or []
    if not reviews:
        return []
    latest = reviews[-1]
    if not latest.get("requires_recovery_cycle"):
        return []
    gaps = latest.get("hard_contract_gaps")
    if not isinstance(gaps, list):
        raise ValueError("review recovery requirement lost its hard contract gaps")
    return [dict(item) for item in gaps]


def _unresolved_hard_gap_sha256s(
    gaps: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
) -> list[str]:
    expected = {stable_sha256(item): item for item in gaps}
    if not expected and resolutions:
        raise ValueError("replay supplied hard gap resolutions without a bound gap")
    states: dict[str, str] = {}
    for item in resolutions:
        identity = _text(item.get("gap_sha256"))
        if identity not in expected:
            raise ValueError("replay resolution references an unknown hard contract gap")
        states[identity] = _text(item.get("status"))
    return [identity for identity in expected if states.get(identity) != "resolved"]


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
        "entry_id": _text(state.get("current_entry_id") or os.environ.get("STATEM_ENTRY_ID")),
    }
    if not all(context.values()):
        raise ValueError("StateM run, node, and entry identity are required")
    return context


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
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
