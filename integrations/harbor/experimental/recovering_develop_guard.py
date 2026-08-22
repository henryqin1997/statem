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

try:
    from integrations.harbor.verification_checks.deadline_status import (
        get_deadline_status,
    )
except ImportError:
    from deadline_status import get_deadline_status  # type: ignore[no-redef]


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
DEFAULT_DEADLINE = Path("/tmp/statem-verification-checks/deadline.json")
DEFAULT_FAMILY_SELECTION = Path(
    "/tmp/statem-verification-checks/family/family-selection.json"
)
DEFAULT_PREFLIGHT_EVIDENCE = Path(
    "/tmp/statem-verification-checks/multirole/preflight-evidence.json"
)
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
INFORMATION_GAIN_FIELDS = {
    "failure_evidence",
    "repair_action",
    "discriminating_check",
    "success_interpretation",
    "failure_interpretation",
    "publicly_evaluable",
    "bounded_scope",
}
INFORMATION_GAIN_TEXT_MAX_CHARS = 800
FAILURE_OWNERS = {
    "implementation_defect": "lead_solver",
    "acceptance_plan_gap": "test_planner",
    "contract_authority_error": "contract_reviewer",
    "evidence_projection_gap": "adapter",
    "orchestration_lifecycle_error": "host",
    "sealed_uncertainty": "acceptance_authority",
    "infrastructure_error": "host",
}
FAILURE_OWNERSHIP_FIELDS = {
    "failure_class",
    "owner_role",
    "observed_failure",
    "causal_hypothesis",
    "repair_action",
    "required_validation_update",
    "confidence",
}
VALIDATION_DELTA_FIELDS = {
    "action",
    "discriminating_check",
    "success_interpretation",
    "failure_interpretation",
    "preserves_prior_obligations",
    "superseded_check_ids",
    "rationale",
}
TARGETED_VALIDATION_DELTA_FIELD = "target_requirement_id"
VALIDATION_ACTIONS = {
    "append_regression",
    "expand_population",
    "repair_invalid_check",
    "clarify_oracle",
    "no_public_delta",
}
RETRY_OWNERS = {"lead_solver", "test_planner", "contract_reviewer"}


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
                require_deadline_budget=args.require_deadline_budget,
                deadline_path=args.deadline,
                family_selection=(
                    _read_json(args.family_selection)
                    if args.require_deadline_budget
                    else None
                ),
            )
            _write_json(args.output, receipt)
        elif args.action == "close":
            receipt = close_cycle(
                ledger_path=args.ledger,
                replay_draft=_read_json(args.replay_draft),
                application=_read_json(args.application),
                artifact_root=args.artifact_root,
                require_information_gain=args.require_information_gain,
                require_failure_closure=args.require_failure_closure,
                require_targeted_validation_delta=(
                    args.require_targeted_validation_delta
                ),
                deadline_path=args.deadline,
                family_selection=(
                    _read_json(args.family_selection)
                    if args.require_failure_closure
                    else None
                ),
                preflight_evidence=(
                    _read_json(args.preflight_evidence)
                    if args.require_targeted_validation_delta
                    else None
                ),
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
    review_route.add_argument(
        "--require-deadline-budget",
        action="store_true",
        help="quarantine instead of revising when a complete revision cannot finish",
    )
    review_route.add_argument("--deadline", type=Path, default=DEFAULT_DEADLINE)
    review_route.add_argument(
        "--family-selection", type=Path, default=DEFAULT_FAMILY_SELECTION
    )
    review_route.add_argument("--output", type=Path, default=DEFAULT_REVIEW_ROUTE)

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    close_parser.add_argument("--replay-draft", type=Path, default=DEFAULT_REPLAY_DRAFT)
    close_parser.add_argument("--application", type=Path, default=DEFAULT_APPLICATION)
    close_parser.add_argument("--artifact-root", type=Path, default=Path("/app"))
    close_parser.add_argument("--output", type=Path, default=DEFAULT_REPLAY_DECISION)
    close_parser.add_argument(
        "--require-information-gain",
        action="store_true",
        help=(
            "authorize another cycle only for a bounded public discriminator "
            "that is bound to the observed failure and concrete repair"
        ),
    )
    close_parser.add_argument(
        "--require-failure-closure",
        action="store_true",
        help=(
            "require a host-validated failure owner and append-only validation "
            "delta before considering another candidate cycle"
        ),
    )
    close_parser.add_argument(
        "--require-targeted-validation-delta",
        action="store_true",
        help=(
            "require every recoverable retry delta to name the existing "
            "candidate-blind requirement that will receive its discriminator"
        ),
    )
    close_parser.add_argument("--deadline", type=Path, default=DEFAULT_DEADLINE)
    close_parser.add_argument(
        "--family-selection", type=Path, default=DEFAULT_FAMILY_SELECTION
    )
    close_parser.add_argument(
        "--preflight-evidence", type=Path, default=DEFAULT_PREFLIGHT_EVIDENCE
    )

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
    require_deadline_budget: bool = False,
    deadline_path: Path = DEFAULT_DEADLINE,
    family_selection: dict[str, Any] | None = None,
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

    acceptance_recovery_gaps = _validated_acceptance_recovery_gaps(
        promotion_decision
    )
    repairable_rejection = _repairable_rejection(
        promotion_decision
    ) or bool(acceptance_recovery_gaps)
    hard_contract_gaps = _validated_hard_contract_gaps(promotion_decision)
    route = "revise" if repairable_rejection else decision
    budget_exhausted = False
    if route == "revise" and len(reviews) >= ledger["max_reviews"]:
        route = "quarantine"
        budget_exhausted = True

    revision_reserve_seconds = 0
    deadline_remaining_seconds: int | None = None
    revision_deadline_feasible = True
    revision_deadline_reason = "not_required"
    deadline_budget_degraded = False
    if route == "revise" and require_deadline_budget:
        family = _normalize_family_selection(family_selection)
        revision_reserve_seconds = family["revision_reserve_seconds"]
        deadline = get_deadline_status(deadline_path)
        if deadline.get("configured"):
            raw_remaining = deadline.get("remaining_seconds")
            deadline_remaining_seconds = (
                int(raw_remaining) if isinstance(raw_remaining, int) else 0
            )
            revision_deadline_feasible = (
                deadline_remaining_seconds >= revision_reserve_seconds
            )
            revision_deadline_reason = (
                "complete_revision_reserve_available"
                if revision_deadline_feasible
                else "insufficient_complete_revision_reserve"
            )
        else:
            revision_deadline_reason = "unbounded_deadline"
        if not revision_deadline_feasible:
            route = "quarantine"
            deadline_budget_degraded = True
    review["status"] = route
    review["promotion_decision_sha256"] = decision_sha256
    review["repairable_rejection"] = repairable_rejection
    review["budget_exhausted"] = budget_exhausted
    review["revision_reserve_seconds"] = revision_reserve_seconds
    review["deadline_remaining_seconds"] = deadline_remaining_seconds
    review["revision_deadline_feasible"] = revision_deadline_feasible
    review["revision_deadline_reason"] = revision_deadline_reason
    review["deadline_budget_degraded"] = deadline_budget_degraded
    review["requires_recovery_cycle"] = bool(
        hard_contract_gaps or acceptance_recovery_gaps
    )
    review["hard_contract_gaps"] = hard_contract_gaps
    review["acceptance_recovery_gaps"] = acceptance_recovery_gaps
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
        "revision_reserve_seconds": review.get("revision_reserve_seconds", 0),
        "deadline_remaining_seconds": review.get("deadline_remaining_seconds"),
        "revision_deadline_feasible": review.get(
            "revision_deadline_feasible", True
        ),
        "revision_deadline_reason": review.get(
            "revision_deadline_reason", "not_required"
        ),
        "deadline_budget_degraded": bool(
            review.get("deadline_budget_degraded")
        ),
        "artifact_disposition": review.get("artifact_disposition"),
        "evaluation_target": review.get("evaluation_target"),
        "requires_recovery_cycle": bool(review.get("requires_recovery_cycle")),
        "hard_contract_gap_sha256s": [
            stable_sha256(item) for item in review.get("hard_contract_gaps") or []
        ],
        "acceptance_recovery_gap_sha256s": [
            stable_sha256(item)
            for item in review.get("acceptance_recovery_gaps") or []
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


def _validated_acceptance_recovery_gaps(
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    reasons = decision.get("reason_codes")
    assessments = decision.get("acceptance_obligation_assessments")
    declared = (
        decision.get("decision") == "revise"
        and isinstance(reasons, list)
        and "acceptance_obligations_unresolved_or_falsified" in reasons
    )
    if not declared or not isinstance(assessments, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in assessments:
        if not isinstance(item, dict):
            continue
        status = _text(item.get("status"))
        evidence_mode = _text(item.get("evidence_mode"))
        requirement_id = _text(item.get("requirement_id"))
        evidence = _text(item.get("evidence"))
        unresolved_reason = _text(item.get("unresolved_reason"))
        independence_basis = _text(item.get("independence_basis"))
        if (
            status not in {"unresolved", "falsified"}
            or evidence_mode != "adapter_replay"
            or not requirement_id
            or not evidence
            or not unresolved_reason
            or not independence_basis
            or requirement_id in seen
        ):
            continue
        seen.add(requirement_id)
        normalized.append(
            {
                "kind": "acceptance_obligation_gap",
                "claim": f"close candidate-blind obligation {requirement_id}",
                "contract_basis": independence_basis,
                "evidence_status": status,
                "evidence_role": evidence_mode,
                "population_access": "observed_public",
                "population_id": requirement_id,
                "observed_evidence": evidence,
                "required_evidence": unresolved_reason,
                "repair_action": (
                    "add a bounded independent adapter replay for acceptance "
                    f"obligation {requirement_id}"
                ),
            }
        )
    return normalized


def close_cycle(
    *,
    ledger_path: Path,
    replay_draft: dict[str, Any],
    application: dict[str, Any],
    artifact_root: Path,
    require_information_gain: bool = False,
    require_failure_closure: bool = False,
    require_targeted_validation_delta: bool = False,
    deadline_path: Path | None = None,
    family_selection: dict[str, Any] | None = None,
    preflight_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    _validate_ledger(ledger)
    _require_receipt(application, "artifact_application_verification")
    context = _state_context()
    if context["node"] != "final_replay":
        raise ValueError("a recovery cycle can only close in final_replay")
    if ledger["run_id"] != context["run_id"]:
        raise ValueError("cycle ledger belongs to another StateM run")
    _validate_replay_draft(
        replay_draft,
        require_information_gain=require_information_gain,
        require_failure_closure=require_failure_closure,
        require_targeted_validation_delta=require_targeted_validation_delta,
    )

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

    recovery_gaps = _latest_recovery_gaps(cycle)
    unresolved_gap_sha256s = _unresolved_hard_gap_sha256s(
        recovery_gaps,
        replay_draft.get("hard_gap_resolutions") or [],
    )
    reported_status = replay_draft["status"]
    effective_status = reported_status
    next_gap = replay_draft["next_gap"]
    if unresolved_gap_sha256s and reported_status == "passed":
        effective_status = "recoverable_failure"
        unresolved = next(
            item
            for item in recovery_gaps
            if stable_sha256(item) == unresolved_gap_sha256s[0]
        )
        next_gap = str(unresolved["repair_action"]).strip()

    failure_ownership = (
        _normalize_failure_ownership(replay_draft.get("failure_ownership"))
        if replay_draft.get("failure_ownership") is not None
        else None
    )
    validation_delta = (
        _normalize_validation_delta(
            replay_draft.get("validation_delta"),
            require_target_requirement=(
                require_targeted_validation_delta
                and replay_draft.get("status") == "recoverable_failure"
            ),
        )
        if replay_draft.get("validation_delta") is not None
        else None
    )
    retry_case = (
        _normalize_information_gain_case(replay_draft.get("retry_case"))
        if replay_draft.get("retry_case") is not None
        else None
    )
    if (
        require_information_gain
        and effective_status == "recoverable_failure"
        and retry_case is None
        and unresolved_gap_sha256s
    ):
        unresolved = next(
            item
            for item in recovery_gaps
            if stable_sha256(item) == unresolved_gap_sha256s[0]
        )
        retry_case = _hard_gap_information_gain_case(
            unresolved,
            failure_evidence=replay_draft["evidence"][0],
        )
    if (
        require_failure_closure
        and effective_status == "recoverable_failure"
        and failure_ownership is None
        and unresolved_gap_sha256s
    ):
        unresolved = next(
            item
            for item in recovery_gaps
            if stable_sha256(item) == unresolved_gap_sha256s[0]
        )
        failure_ownership, validation_delta = _hard_gap_failure_closure(
            unresolved,
            failure_evidence=replay_draft["evidence"][0],
            require_target_requirement=require_targeted_validation_delta,
        )
    if require_failure_closure and effective_status != "passed":
        if failure_ownership is None or validation_delta is None:
            raise ValueError("failed replay requires failure ownership and validation delta")
        if failure_ownership["observed_failure"] not in replay_draft["evidence"]:
            raise ValueError("failure ownership is not bound to replay evidence")
        if (
            effective_status == "recoverable_failure"
            and failure_ownership["repair_action"] != next_gap
        ):
            raise ValueError("failure ownership repair action is not bound to next_gap")
        if failure_ownership["required_validation_update"] != validation_delta["rationale"]:
            raise ValueError("failure ownership is not bound to the validation delta")
        if not validation_delta["preserves_prior_obligations"]:
            raise ValueError("validation delta must preserve prior contract obligations")
        _validate_failure_delta_pair(failure_ownership, validation_delta)
        if effective_status == "recoverable_failure":
            retry_case = _failure_closure_information_gain_case(
                failure_ownership=failure_ownership,
                validation_delta=validation_delta,
            )
            if (
                require_targeted_validation_delta
                and failure_ownership["owner_role"] in RETRY_OWNERS
            ):
                _validate_target_requirement(
                    preflight_evidence=preflight_evidence,
                    validation_delta=validation_delta,
                )

    information_gain_authorized = True
    information_gain_reason = "not_required"
    information_gain_identity = ""
    if require_information_gain and effective_status == "recoverable_failure":
        (
            information_gain_authorized,
            information_gain_reason,
            information_gain_identity,
        ) = _authorize_information_gain(
            retry_case=retry_case,
            replay_evidence=replay_draft["evidence"],
            next_gap=next_gap,
            prior_cycles=ledger["cycles"][:-1],
        )

    family = (
        _normalize_family_selection(family_selection)
        if require_failure_closure
        else None
    )
    failure_owner_authorized = True
    failure_owner_reason = "not_required"
    if require_failure_closure and effective_status == "recoverable_failure":
        owner = failure_ownership["owner_role"] if failure_ownership else ""
        failure_owner_authorized = owner in RETRY_OWNERS
        failure_owner_reason = (
            "cycle_recoverable_owner"
            if failure_owner_authorized
            else f"owner_{owner}_requires_external_control"
        )

    deadline_feasible = True
    deadline_reason = "not_required"
    deadline_remaining_seconds: int | None = None
    retry_reserve_seconds = family["retry_reserve_seconds"] if family else 0
    if require_failure_closure and effective_status == "recoverable_failure":
        deadline = get_deadline_status(deadline_path or DEFAULT_DEADLINE)
        if deadline.get("configured"):
            raw_remaining = deadline.get("remaining_seconds")
            deadline_remaining_seconds = (
                int(raw_remaining) if isinstance(raw_remaining, int) else 0
            )
            deadline_feasible = deadline_remaining_seconds >= retry_reserve_seconds
            deadline_reason = (
                "full_cycle_reserve_available"
                if deadline_feasible
                else "insufficient_full_cycle_reserve"
            )
        else:
            deadline_reason = "unbounded_deadline"

    cycle["status"] = effective_status
    cycle["reported_status"] = reported_status
    cycle["replay_entry_id"] = context["entry_id"]
    cycle["replay_draft_sha256"] = replay_draft_sha256
    cycle["application_sha256"] = application_sha256
    cycle["selected_artifact_identity"] = observed
    cycle["evidence"] = list(replay_draft["evidence"])
    cycle["residual_risk"] = list(replay_draft["residual_risk"])
    cycle["next_gap"] = next_gap
    cycle["retry_case"] = retry_case
    cycle["information_gain_required"] = require_information_gain
    cycle["information_gain_authorized"] = information_gain_authorized
    cycle["information_gain_reason"] = information_gain_reason
    cycle["information_gain_identity"] = information_gain_identity
    cycle["failure_ownership"] = failure_ownership
    cycle["validation_delta"] = validation_delta
    cycle["failure_closure_sha256"] = (
        stable_sha256(
            {
                "failure_ownership": failure_ownership,
                "validation_delta": validation_delta,
            }
        )
        if failure_ownership is not None and validation_delta is not None
        else ""
    )
    cycle["failure_owner_authorized"] = failure_owner_authorized
    cycle["failure_owner_reason"] = failure_owner_reason
    cycle["family_id"] = family["family_id"] if family else ""
    cycle["retry_reserve_seconds"] = retry_reserve_seconds
    cycle["deadline_remaining_seconds"] = deadline_remaining_seconds
    cycle["deadline_feasible"] = deadline_feasible
    cycle["deadline_reason"] = deadline_reason
    cycle["hard_gap_resolutions"] = list(replay_draft.get("hard_gap_resolutions") or [])
    cycle["unresolved_recovery_gap_sha256s"] = unresolved_gap_sha256s
    hard_gap_sha256s = {
        stable_sha256(item)
        for item in recovery_gaps
        if item.get("kind") != "acceptance_obligation_gap"
    }
    cycle["unresolved_hard_gap_sha256s"] = [
        identity
        for identity in unresolved_gap_sha256s
        if identity in hard_gap_sha256s
    ]
    cycle["closed_at"] = _now()

    can_retry = (
        effective_status == "recoverable_failure"
        and len(ledger["cycles"]) < ledger["max_cycles"]
        and information_gain_authorized
        and failure_owner_authorized
        and deadline_feasible
    )
    action = "retry" if can_retry else "handoff"
    cycle["action"] = action
    if effective_status == "recoverable_failure" and not can_retry:
        if len(ledger["cycles"]) >= ledger["max_cycles"]:
            cycle["residual_risk"].append("recovery cycle budget exhausted")
        elif not information_gain_authorized:
            cycle["residual_risk"].append(
                f"information gain gate declined retry: {information_gain_reason}"
            )
        elif not failure_owner_authorized:
            cycle["residual_risk"].append(
                f"failure owner gate declined task cycle: {failure_owner_reason}"
            )
        elif not deadline_feasible:
            cycle["residual_risk"].append(
                "deadline gate declined retry: insufficient time for a full family cycle"
            )
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
        "unresolved_recovery_gap_sha256s": cycle.get(
            "unresolved_recovery_gap_sha256s",
            cycle.get("unresolved_hard_gap_sha256s", []),
        ),
        "information_gain_required": cycle.get("information_gain_required", False),
        "information_gain_authorized": cycle.get(
            "information_gain_authorized", True
        ),
        "information_gain_reason": cycle.get("information_gain_reason", "not_required"),
        "information_gain_identity": cycle.get("information_gain_identity", ""),
        "failure_ownership": cycle.get("failure_ownership"),
        "validation_delta": cycle.get("validation_delta"),
        "failure_closure_sha256": cycle.get("failure_closure_sha256", ""),
        "failure_owner_authorized": cycle.get("failure_owner_authorized", True),
        "failure_owner_reason": cycle.get("failure_owner_reason", "not_required"),
        "family_id": cycle.get("family_id", ""),
        "retry_reserve_seconds": cycle.get("retry_reserve_seconds", 0),
        "deadline_remaining_seconds": cycle.get("deadline_remaining_seconds"),
        "deadline_feasible": cycle.get("deadline_feasible", True),
        "deadline_reason": cycle.get("deadline_reason", "not_required"),
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


def _validate_replay_draft(
    draft: dict[str, Any],
    *,
    require_information_gain: bool = False,
    require_failure_closure: bool = False,
    require_targeted_validation_delta: bool = False,
) -> None:
    required = {"status", "evidence", "residual_risk", "next_gap"}
    allowed = required | {"hard_gap_resolutions"}
    if require_information_gain and not require_failure_closure:
        required.add("retry_case")
        allowed.add("retry_case")
    if require_failure_closure:
        required.update({"failure_ownership", "validation_delta"})
        allowed.update({"failure_ownership", "validation_delta"})
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
    if require_information_gain and not require_failure_closure:
        retry_case = draft.get("retry_case")
        if draft["status"] == "recoverable_failure":
            _normalize_information_gain_case(retry_case)
        elif retry_case is not None:
            raise ValueError("retry_case is only valid for recoverable_failure")
    if require_failure_closure:
        ownership = draft.get("failure_ownership")
        delta = draft.get("validation_delta")
        if draft["status"] == "passed":
            if ownership is not None or delta is not None:
                raise ValueError("passed replay cannot claim failure ownership or validation delta")
        else:
            _normalize_failure_ownership(ownership)
            _normalize_validation_delta(
                delta,
                require_target_requirement=(
                    require_targeted_validation_delta
                    and draft["status"] == "recoverable_failure"
                ),
            )
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


def _normalize_information_gain_case(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != INFORMATION_GAIN_FIELDS:
        raise ValueError(
            "retry_case requires exactly " + ", ".join(sorted(INFORMATION_GAIN_FIELDS))
        )
    normalized: dict[str, Any] = {}
    for field in sorted(INFORMATION_GAIN_FIELDS - {"publicly_evaluable", "bounded_scope"}):
        text = _text(value.get(field))
        if not text or len(text) > INFORMATION_GAIN_TEXT_MAX_CHARS:
            raise ValueError(f"retry_case {field} must be bounded non-empty text")
        normalized[field] = text
    for field in ("publicly_evaluable", "bounded_scope"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"retry_case {field} must be boolean")
        normalized[field] = value[field]
    return normalized


def _normalize_failure_ownership(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FAILURE_OWNERSHIP_FIELDS:
        raise ValueError(
            "failure_ownership requires exactly "
            + ", ".join(sorted(FAILURE_OWNERSHIP_FIELDS))
        )
    failure_class = _text(value.get("failure_class"))
    if failure_class not in FAILURE_OWNERS:
        raise ValueError("failure_ownership failure_class is invalid")
    owner_role = _text(value.get("owner_role"))
    if owner_role != FAILURE_OWNERS[failure_class]:
        raise ValueError(
            f"failure class {failure_class!r} must be owned by {FAILURE_OWNERS[failure_class]!r}"
        )
    confidence = _text(value.get("confidence"))
    if confidence not in {"low", "medium", "high"}:
        raise ValueError("failure_ownership confidence must be low, medium, or high")
    normalized = {
        "failure_class": failure_class,
        "owner_role": owner_role,
        "confidence": confidence,
    }
    for field in sorted(
        FAILURE_OWNERSHIP_FIELDS - {"failure_class", "owner_role", "confidence"}
    ):
        text = _text(value.get(field))
        if not text or len(text) > INFORMATION_GAIN_TEXT_MAX_CHARS:
            raise ValueError(f"failure_ownership {field} must be bounded non-empty text")
        normalized[field] = text
    return normalized


def _normalize_validation_delta(
    value: Any,
    *,
    require_target_requirement: bool = False,
) -> dict[str, Any]:
    fields = set(value) if isinstance(value, dict) else set()
    allowed_fields = VALIDATION_DELTA_FIELDS | {TARGETED_VALIDATION_DELTA_FIELD}
    expected_fields = (
        allowed_fields if require_target_requirement else VALIDATION_DELTA_FIELDS
    )
    if (
        not isinstance(value, dict)
        or fields != expected_fields
    ):
        raise ValueError(
            "validation_delta requires exactly the base fields"
            + (
                " plus target_requirement_id"
                if require_target_requirement
                else " without target_requirement_id"
            )
        )
    action = _text(value.get("action"))
    if action not in VALIDATION_ACTIONS:
        raise ValueError("validation_delta action is invalid")
    if not isinstance(value.get("preserves_prior_obligations"), bool):
        raise ValueError("validation_delta preserves_prior_obligations must be boolean")
    superseded = value.get("superseded_check_ids")
    if not isinstance(superseded, list) or not all(_text(item) for item in superseded):
        raise ValueError("validation_delta superseded_check_ids must be a string list")
    if superseded and action != "repair_invalid_check":
        raise ValueError("only repair_invalid_check may supersede prior checks")
    normalized: dict[str, Any] = {
        "action": action,
        "preserves_prior_obligations": value["preserves_prior_obligations"],
        "superseded_check_ids": [_text(item) for item in superseded],
    }
    if TARGETED_VALIDATION_DELTA_FIELD in value:
        target_requirement_id = _text(value.get(TARGETED_VALIDATION_DELTA_FIELD))
        if (
            not target_requirement_id
            or len(target_requirement_id) > INFORMATION_GAIN_TEXT_MAX_CHARS
        ):
            raise ValueError(
                "validation_delta target_requirement_id must be bounded non-empty text"
            )
        normalized[TARGETED_VALIDATION_DELTA_FIELD] = target_requirement_id
    for field in sorted(
        VALIDATION_DELTA_FIELDS
        - {"action", "preserves_prior_obligations", "superseded_check_ids"}
    ):
        text = _text(value.get(field))
        if not text or len(text) > INFORMATION_GAIN_TEXT_MAX_CHARS:
            raise ValueError(f"validation_delta {field} must be bounded non-empty text")
        normalized[field] = text
    return normalized


def _validate_target_requirement(
    *,
    preflight_evidence: dict[str, Any] | None,
    validation_delta: dict[str, Any],
) -> None:
    if (
        not isinstance(preflight_evidence, dict)
        or preflight_evidence.get("version") != 1
        or preflight_evidence.get("kind") != "plan_preflight_evidence"
    ):
        raise ValueError(
            "targeted validation delta requires version-1 preflight evidence"
        )
    target = _text(validation_delta.get(TARGETED_VALIDATION_DELTA_FIELD))
    if not target:
        raise ValueError("recoverable validation delta requires target_requirement_id")
    plan = preflight_evidence.get("acceptance_plan")
    requirements = plan.get("requirements") if isinstance(plan, dict) else None
    if not isinstance(requirements, list):
        raise ValueError("preflight evidence is missing candidate-blind requirements")
    requirement_ids = [_preflight_requirement_id(item) for item in requirements]
    if len(set(requirement_ids)) != len(requirement_ids):
        raise ValueError("preflight evidence has duplicate requirement identities")
    if target not in requirement_ids:
        raise ValueError(
            "validation delta target_requirement_id is not in the bound preflight plan"
        )


def _preflight_requirement_id(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("candidate-blind requirements must be JSON objects")
    identifier = _text(value.get("requirement_id"))
    if not identifier:
        raise ValueError("candidate-blind requirement_id is required")
    strata = value.get("required_strata")
    if not isinstance(strata, list) or not all(_text(item) for item in strata):
        raise ValueError("candidate-blind required_strata must be a string list")
    return identifier


def _normalize_family_selection(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or value.get("kind") != "develop_family_selection"
    ):
        raise ValueError("failure closure requires a version-1 develop family selection")
    family_id = _text(value.get("family_id"))
    reserve = value.get("retry_reserve_seconds")
    if not family_id or not isinstance(reserve, int) or reserve < 300:
        raise ValueError("develop family selection has an invalid retry reserve")
    revision_reserve = value.get("revision_reserve_seconds", reserve)
    if (
        not isinstance(revision_reserve, int)
        or revision_reserve < 300
        or revision_reserve > reserve
    ):
        raise ValueError("develop family selection has an invalid revision reserve")
    return {
        "family_id": family_id,
        "retry_reserve_seconds": reserve,
        "revision_reserve_seconds": revision_reserve,
    }


def _validate_failure_delta_pair(
    failure_ownership: dict[str, Any],
    validation_delta: dict[str, Any],
) -> None:
    allowed_actions = {
        "implementation_defect": {"append_regression", "expand_population"},
        "acceptance_plan_gap": {
            "expand_population",
            "repair_invalid_check",
            "clarify_oracle",
        },
        "contract_authority_error": {"clarify_oracle", "append_regression"},
        "evidence_projection_gap": {"no_public_delta"},
        "orchestration_lifecycle_error": {"no_public_delta"},
        "sealed_uncertainty": {"no_public_delta"},
        "infrastructure_error": {"no_public_delta"},
    }
    failure_class = failure_ownership["failure_class"]
    action = validation_delta["action"]
    if action not in allowed_actions[failure_class]:
        raise ValueError(
            f"failure class {failure_class!r} cannot use validation action {action!r}"
        )


def _failure_closure_information_gain_case(
    *,
    failure_ownership: dict[str, Any],
    validation_delta: dict[str, Any],
) -> dict[str, Any]:
    owner = failure_ownership["owner_role"]
    action = validation_delta["action"]
    publicly_evaluable = owner in RETRY_OWNERS and action != "no_public_delta"
    return {
        "failure_evidence": failure_ownership["observed_failure"],
        "repair_action": failure_ownership["repair_action"],
        "discriminating_check": validation_delta["discriminating_check"],
        "success_interpretation": validation_delta["success_interpretation"],
        "failure_interpretation": validation_delta["failure_interpretation"],
        "publicly_evaluable": publicly_evaluable,
        "bounded_scope": validation_delta["preserves_prior_obligations"],
    }


def _hard_gap_failure_closure(
    gap: dict[str, Any],
    *,
    failure_evidence: str,
    require_target_requirement: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    is_public = gap.get("population_access") == "observed_public"
    failure_class = "acceptance_plan_gap" if is_public else "sealed_uncertainty"
    owner_role = FAILURE_OWNERS[failure_class]
    repair_action = _text(gap.get("repair_action"))
    required_evidence = _text(gap.get("required_evidence"))
    validation_rationale = (
        "append the unresolved public acceptance population to the next candidate-blind plan"
        if is_public
        else "record the sealed population as residual uncertainty without inventing a public proxy"
    )
    ownership = {
        "failure_class": failure_class,
        "owner_role": owner_role,
        "observed_failure": failure_evidence,
        "causal_hypothesis": _text(gap.get("observed_evidence")),
        "repair_action": repair_action,
        "required_validation_update": validation_rationale,
        "confidence": "high" if is_public else "medium",
    }
    delta = {
        "action": "expand_population" if is_public else "no_public_delta",
        "discriminating_check": required_evidence,
        "success_interpretation": "fresh independent evidence resolves the bound acceptance gap",
        "failure_interpretation": _text(gap.get("observed_evidence")),
        "preserves_prior_obligations": True,
        "superseded_check_ids": [],
        "rationale": validation_rationale,
    }
    if is_public and require_target_requirement:
        delta[TARGETED_VALIDATION_DELTA_FIELD] = _text(gap.get("population_id"))
    return _normalize_failure_ownership(ownership), _normalize_validation_delta(
        delta,
        require_target_requirement=(is_public and require_target_requirement),
    )


def _authorize_information_gain(
    *,
    retry_case: dict[str, Any] | None,
    replay_evidence: list[str],
    next_gap: str,
    prior_cycles: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    if retry_case is None:
        return False, "missing_retry_case", ""
    if not retry_case["publicly_evaluable"]:
        return False, "not_publicly_evaluable", ""
    if not retry_case["bounded_scope"]:
        return False, "unbounded_repair_scope", ""
    if retry_case["failure_evidence"] not in replay_evidence:
        return False, "failure_evidence_not_bound", ""
    if retry_case["repair_action"] != next_gap:
        return False, "repair_action_not_bound", ""
    if (
        retry_case["success_interpretation"].casefold()
        == retry_case["failure_interpretation"].casefold()
    ):
        return False, "non_discriminating_outcomes", ""
    identity = stable_sha256(
        {
            "discriminating_check": retry_case["discriminating_check"].casefold(),
            "success_interpretation": retry_case["success_interpretation"].casefold(),
            "failure_interpretation": retry_case["failure_interpretation"].casefold(),
        }
    )
    prior_identities = {
        _text(cycle.get("information_gain_identity"))
        for cycle in prior_cycles
        if _text(cycle.get("information_gain_identity"))
    }
    if identity in prior_identities:
        return False, "duplicate_discriminator", identity
    return True, "novel_bounded_public_discriminator", identity


def _hard_gap_information_gain_case(
    gap: dict[str, Any],
    *,
    failure_evidence: str,
) -> dict[str, Any]:
    return {
        "failure_evidence": failure_evidence,
        "repair_action": _text(gap.get("repair_action")),
        "discriminating_check": _text(gap.get("required_evidence")),
        "success_interpretation": "fresh acceptance evidence resolves the bound hard gap",
        "failure_interpretation": _text(gap.get("observed_evidence")),
        "publicly_evaluable": gap.get("population_access") == "observed_public",
        "bounded_scope": True,
    }


def _latest_hard_contract_gaps(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    return _latest_recovery_gaps(cycle)


def _latest_recovery_gaps(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = cycle.get("reviews") or []
    if not reviews:
        return []
    latest = reviews[-1]
    if not latest.get("requires_recovery_cycle"):
        return []
    hard_gaps = latest.get("hard_contract_gaps") or []
    acceptance_gaps = latest.get("acceptance_recovery_gaps") or []
    if not isinstance(hard_gaps, list) or not isinstance(acceptance_gaps, list):
        raise ValueError("review recovery requirement lost its structured gaps")
    return [dict(item) for item in [*hard_gaps, *acceptance_gaps]]


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
