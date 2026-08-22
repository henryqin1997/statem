from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


DEFAULT_DIR = Path("/tmp/statem-verification-checks")
DEFAULT_PROMOTION_DECISION = DEFAULT_DIR / "multirole/promotion-decision.json"
DEFAULT_REVIEW_ROUTE = DEFAULT_DIR / "recovering-develop/review-route.json"
DEFAULT_ACCEPTANCE_REPLAY = DEFAULT_DIR / "multirole/acceptance-replay.json"
DEFAULT_REPLAY_DECISION = DEFAULT_DIR / "recovering-develop/replay-decision.json"
DEFAULT_PROVIDER_APPLICATION = DEFAULT_DIR / "artifact-provider/application.json"
DEFAULT_OUTPUT = DEFAULT_DIR / "submission/submission-eligibility.json"

POLICIES = {"strict_review", "deadline_best_validated"}
ROUTES = {"promote", "revise", "quarantine", "rollback"}
TARGETS = {"candidate", "baseline", "none"}
SEMANTIC_POLICY_CHECKS = {
    "all_acceptance_obligations_satisfied",
    "contract_preserved",
    "counterevidence_present",
    "no_blocking_contract_violations",
    "no_blocking_regressions",
    "no_hard_contract_gaps",
    "protected_claims_corroborated",
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "decide":
            receipt = decide_submission(
                promotion_decision=_read_json(args.promotion_decision),
                review_route=_read_json(args.review_route),
                acceptance_replay=_read_optional_json(args.acceptance_replay),
                replay_decision=_read_optional_json(args.replay_decision),
                provider_application=_read_optional_json(args.provider_application),
                policy=args.policy,
            )
            receipt = _reuse_equivalent_receipt(
                args.output,
                receipt,
                volatile_fields={"created_at"},
            )
            _write_json(args.output, receipt)
        elif args.action == "require":
            receipt = _read_json(args.decision)
            require_submission(
                receipt,
                allowed_targets=set(args.allow_target),
                require_handoff=args.require_handoff,
                require_fallback=args.require_fallback,
            )
        else:
            parser.error(f"unknown action: {args.action}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"submission eligibility gate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Separate candidate promotion, diagnostic replay, and final "
            "submission eligibility."
        )
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    decide = subparsers.add_parser("decide")
    decide.add_argument(
        "--promotion-decision", type=Path, default=DEFAULT_PROMOTION_DECISION
    )
    decide.add_argument("--review-route", type=Path, default=DEFAULT_REVIEW_ROUTE)
    decide.add_argument(
        "--acceptance-replay", type=Path, default=DEFAULT_ACCEPTANCE_REPLAY
    )
    decide.add_argument(
        "--replay-decision", type=Path, default=DEFAULT_REPLAY_DECISION
    )
    decide.add_argument(
        "--provider-application", type=Path, default=DEFAULT_PROVIDER_APPLICATION
    )
    decide.add_argument(
        "--policy",
        choices=sorted(POLICIES),
        default="deadline_best_validated",
    )
    decide.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    require = subparsers.add_parser("require")
    require.add_argument("--decision", type=Path, default=DEFAULT_OUTPUT)
    require.add_argument(
        "--allow-target",
        action="append",
        choices=sorted(TARGETS),
        required=True,
    )
    require.add_argument("--require-handoff", action="store_true")
    require.add_argument("--require-fallback", action="store_true")
    return parser


def decide_submission(
    *,
    promotion_decision: dict[str, Any],
    review_route: dict[str, Any],
    acceptance_replay: dict[str, Any] | None,
    replay_decision: dict[str, Any] | None,
    provider_application: dict[str, Any] | None,
    policy: str = "deadline_best_validated",
) -> dict[str, Any]:
    if policy not in POLICIES:
        raise ValueError(f"unsupported submission policy: {policy}")
    _require_receipt(promotion_decision, "promotion_authorization")
    _require_receipt(review_route, "recovering_develop_review_route")
    run_id = _text(promotion_decision.get("run_id"))
    if not run_id:
        raise ValueError("promotion decision has no run id")
    _require_same_run(run_id, review_route, "review route")
    if review_route.get("promotion_decision_sha256") != stable_sha256(
        promotion_decision
    ):
        raise ValueError("review route is not bound to the promotion decision")
    if review_route.get("promotion_decision") != promotion_decision.get("decision"):
        raise ValueError("review route and promotion decision disagree")

    route = _text(review_route.get("route"))
    if route not in ROUTES:
        raise ValueError("review route is invalid")
    candidate_identity = _identity(
        promotion_decision, "candidate_artifact_identity"
    )
    baseline_identity = _identity(
        promotion_decision, "baseline_artifact_identity"
    )
    review_mechanically_valid = _review_mechanically_valid(promotion_decision)
    blocker_codes = _semantic_blocker_codes(promotion_decision)
    advisory_codes = _advisory_uncertainty_codes(promotion_decision)
    no_semantic_blockers = not blocker_codes

    acceptance_passed = _candidate_acceptance_passed(
        acceptance_replay,
        run_id=run_id,
        candidate_identity=candidate_identity,
    )
    final_replay_passed = _final_replay_passed(
        replay_decision,
        run_id=run_id,
    )
    public_replay_passed = _public_replay_passed(
        replay_decision,
        run_id=run_id,
    )
    candidate_validated = acceptance_passed and final_replay_passed

    promotion_authorized = bool(
        promotion_decision.get("decision") == "promote"
        and route == "promote"
        and review_mechanically_valid
        and no_semantic_blockers
    )
    diagnostic_replay_eligible = bool(
        candidate_identity and route in {"promote", "revise", "quarantine"}
    )

    deadline_candidate_eligible = bool(
        policy == "deadline_best_validated"
        and route == "quarantine"
        and review_mechanically_valid
        and no_semantic_blockers
        and acceptance_passed
        and public_replay_passed
        and promotion_decision.get("decision") == "revise"
        and promotion_decision.get("falsifier_verdict") in {"accept", "inconclusive"}
        and (
            review_route.get("review_budget_exhausted") is True
            or review_route.get("deadline_budget_degraded") is True
        )
    )
    promotion_eligible = bool(promotion_authorized and candidate_validated)
    candidate_submission_eligible = bool(
        promotion_eligible or deadline_candidate_eligible
    )

    reasons = list(blocker_codes)
    reasons.extend(advisory_codes)
    if not review_mechanically_valid:
        reasons.append("review_receipt_invalid")
    if not acceptance_passed:
        reasons.append("candidate_acceptance_replay_not_passed")
    if not final_replay_passed:
        reasons.append("final_replay_not_strictly_passed")
    if not public_replay_passed:
        reasons.append("public_replay_not_passed")
    if promotion_authorized and not promotion_eligible:
        reasons.append("promotion_authorization_revoked_by_replay")

    if candidate_submission_eligible:
        selected_target = "candidate"
        selected_identity = candidate_identity
        allowed_provider_modes = (
            {"activate"} if promotion_eligible else {"quarantine"}
        )
        reasons.append(
            "candidate_promoted"
            if promotion_eligible
            else "deadline_quarantine_candidate_validated"
        )
    elif route in {"quarantine", "rollback", "promote"}:
        selected_target = "baseline"
        selected_identity = baseline_identity
        allowed_provider_modes = {"restore"}
        reasons.append(
            "quarantine_diagnostic_only_strict_review"
            if route == "quarantine" and policy == "strict_review"
            else "candidate_ineligible_baseline_fallback"
        )
    else:
        selected_target = "none"
        selected_identity = ""
        allowed_provider_modes = set()
        reasons.append("revision_required_before_submission")

    application_verified = _application_matches(
        provider_application,
        run_id=run_id,
        selected_identity=selected_identity,
        allowed_modes=allowed_provider_modes,
    )
    submission_eligible = bool(selected_target != "none" and application_verified)
    fallback_required = bool(
        selected_target == "baseline" and not application_verified
    )
    if selected_target != "none" and not application_verified:
        reasons.append("submission_target_not_applied")
    elif selected_target == "baseline":
        reasons.append("baseline_fallback_verified")

    return {
        "version": 1,
        "kind": "submission_eligibility_decision",
        "run_id": run_id,
        "policy": policy,
        "promotion_decision_sha256": stable_sha256(promotion_decision),
        "review_route_sha256": stable_sha256(review_route),
        "acceptance_replay_sha256": (
            stable_sha256(acceptance_replay) if acceptance_replay is not None else None
        ),
        "replay_decision_sha256": (
            stable_sha256(replay_decision) if replay_decision is not None else None
        ),
        "provider_application_sha256": (
            stable_sha256(provider_application)
            if provider_application is not None
            else None
        ),
        "review_route": route,
        "promotion_authorized": promotion_authorized,
        "promotion_eligible": promotion_eligible,
        "diagnostic_replay_eligible": diagnostic_replay_eligible,
        "candidate_submission_eligible": candidate_submission_eligible,
        "selected_submission_target": selected_target,
        "selected_submission_identity": selected_identity,
        "required_provider_modes": sorted(allowed_provider_modes),
        "submission_application_verified": application_verified,
        "submission_eligible": submission_eligible,
        "handoff_eligible": submission_eligible,
        "fallback_required": fallback_required,
        "review_mechanically_valid": review_mechanically_valid,
        "candidate_acceptance_passed": acceptance_passed,
        "final_replay_passed": final_replay_passed,
        "public_replay_passed": public_replay_passed,
        "semantic_blocker_codes": blocker_codes,
        "advisory_uncertainty_codes": advisory_codes,
        "reason_codes": sorted(set(reasons)),
        "created_at": _now(),
    }


def require_submission(
    decision: dict[str, Any],
    *,
    allowed_targets: set[str],
    require_handoff: bool = False,
    require_fallback: bool = False,
) -> None:
    _require_receipt(decision, "submission_eligibility_decision")
    target = decision.get("selected_submission_target")
    if target not in allowed_targets:
        raise ValueError(
            f"submission target {target!r} is not allowed; expected {sorted(allowed_targets)}"
        )
    if require_handoff and decision.get("handoff_eligible") is not True:
        raise ValueError("submission target is not verified for handoff")
    if require_fallback and decision.get("fallback_required") is not True:
        raise ValueError("submission target does not require provider fallback")


def _review_mechanically_valid(decision: dict[str, Any]) -> bool:
    checks = decision.get("checks")
    mechanical_checks = (
        {
            key: value
            for key, value in checks.items()
            if key not in SEMANTIC_POLICY_CHECKS
        }
        if isinstance(checks, dict)
        else {}
    )
    return bool(
        mechanical_checks
        and all(value is True for value in mechanical_checks.values())
    )


def _semantic_blocker_codes(decision: dict[str, Any]) -> list[str]:
    fields = {
        "blocking_contract_violations": "blocking_contract_violation",
        "blocking_regressions": "blocking_regression",
        "hard_contract_gaps": "hard_contract_gap",
    }
    reasons = [
        reason
        for field, reason in fields.items()
        if isinstance(decision.get(field), list) and decision.get(field)
    ]
    assessments = decision.get("acceptance_obligation_assessments")
    if isinstance(assessments, list) and any(
        isinstance(item, dict)
        and item.get("status") == "falsified"
        for item in assessments
    ):
        reasons.append("acceptance_obligation_falsified")
    protections = decision.get("protection_assessments")
    if isinstance(protections, list) and any(
        isinstance(item, dict) and item.get("status") == "falsified"
        for item in protections
    ):
        reasons.append("protected_behavior_falsified")
    return sorted(set(reasons))


def _advisory_uncertainty_codes(decision: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    assessments = decision.get("acceptance_obligation_assessments")
    if isinstance(assessments, list) and any(
        isinstance(item, dict) and item.get("status") == "unresolved"
        for item in assessments
    ):
        reasons.append("acceptance_obligation_unresolved")
    protections = decision.get("protection_assessments")
    if isinstance(protections, list) and any(
        isinstance(item, dict) and item.get("status") == "unresolved"
        for item in protections
    ):
        reasons.append("protected_behavior_unresolved")
    if isinstance(decision.get("sealed_acceptance_uncertainties"), list) and decision.get(
        "sealed_acceptance_uncertainties"
    ):
        reasons.append("sealed_acceptance_uncertainty")
    return sorted(set(reasons))


def _candidate_acceptance_passed(
    receipt: dict[str, Any] | None,
    *,
    run_id: str,
    candidate_identity: str,
) -> bool:
    if receipt is None:
        return False
    _require_receipt(receipt, "candidate_acceptance_replay")
    _require_same_run(run_id, receipt, "candidate acceptance replay")
    if receipt.get("candidate_artifact_identity") != candidate_identity:
        raise ValueError("acceptance replay is not bound to the candidate")
    return bool(
        receipt.get("execution_complete") is True
        and receipt.get("all_passed") is True
        and receipt.get("overall_status") == "passed"
    )


def _final_replay_passed(
    receipt: dict[str, Any] | None,
    *,
    run_id: str,
) -> bool:
    if receipt is None:
        return False
    _require_receipt(receipt, "recovering_develop_replay_decision")
    _require_same_run(run_id, receipt, "final replay decision")
    return bool(receipt.get("status") == "passed" and receipt.get("action") == "handoff")


def _public_replay_passed(
    receipt: dict[str, Any] | None,
    *,
    run_id: str,
) -> bool:
    if receipt is None:
        return False
    _require_receipt(receipt, "recovering_develop_replay_decision")
    _require_same_run(run_id, receipt, "final replay decision")
    observed_status = receipt.get("reported_status", receipt.get("status"))
    return bool(observed_status == "passed" and receipt.get("action") == "handoff")


def _application_matches(
    receipt: dict[str, Any] | None,
    *,
    run_id: str,
    selected_identity: str,
    allowed_modes: set[str],
) -> bool:
    if not selected_identity or receipt is None:
        return False
    _require_receipt(receipt, "filesystem_artifact_application")
    _require_same_run(run_id, receipt, "provider application")
    return bool(
        receipt.get("verified") is True
        and receipt.get("mode") in allowed_modes
        and receipt.get("expected_artifact_identity") == selected_identity
        and receipt.get("observed_artifact_identity") == selected_identity
    )


def _identity(receipt: dict[str, Any], field: str) -> str:
    value = _text(receipt.get(field))
    if not value:
        raise ValueError(f"{field} is missing")
    return value


def _require_receipt(receipt: dict[str, Any], kind: str) -> None:
    if not isinstance(receipt, dict) or receipt.get("kind") != kind:
        raise ValueError(f"expected {kind} receipt")


def _require_same_run(run_id: str, receipt: dict[str, Any], label: str) -> None:
    if receipt.get("run_id") != run_id:
        raise ValueError(f"{label} belongs to another StateM run")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    return _read_json(path) if path.exists() else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _reuse_equivalent_receipt(
    path: Path,
    value: dict[str, Any],
    *,
    volatile_fields: set[str],
) -> dict[str, Any]:
    if not path.is_file():
        return value
    try:
        existing = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return value
    if any(not _text(existing.get(field)) for field in volatile_fields):
        return value
    existing_stable = {
        key: item for key, item in existing.items() if key not in volatile_fields
    }
    value_stable = {
        key: item for key, item in value.items() if key not in volatile_fields
    }
    return existing if existing_stable == value_stable else value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
