from __future__ import annotations

import hashlib
import json
from typing import Any


LANES = {"scoring", "develop", "safety"}
FAILURE_OWNERS = {
    "capability",
    "hardware",
    "infrastructure",
    "protocol",
    "controller",
    "solver_direction",
    "implementation",
    "validation",
    "routing",
    "context_burden",
}
CLAIM_SCOPES = {"task_boundary", "family_general", "negative_transfer"}
NO_ROLLOUT_OWNERS = {"infrastructure", "protocol", "controller", "routing"}


def stable_identity(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_adapted_contrast(
    negative: dict[str, Any],
    positive: dict[str, Any],
) -> dict[str, Any]:
    """Summarize a causal contrast without promoting it into score evidence."""

    changed_controls = sorted(
        set(positive.get("active_controls") or [])
        ^ set(negative.get("active_controls") or [])
    )
    comparable_fields = (
        "task_family",
        "model",
        "reasoning_effort",
        "platform_class",
        "timeout_multiplier",
        "retry_policy",
    )
    confounders = [
        field
        for field in comparable_fields
        if negative.get(field) != positive.get(field)
    ]
    return {
        "version": 1,
        "kind": "tb3_adapted_contrast",
        "score_eligible": False,
        "negative_identity": stable_identity(negative),
        "positive_identity": stable_identity(positive),
        "changed_controls": changed_controls,
        "confounders": confounders,
        "causal_status": (
            "isolated_candidate"
            if len(changed_controls) == 1 and not confounders
            else "confounded"
        ),
        "raw_delta": _reward(positive) - _reward(negative),
    }


def validate_practice_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "version",
        "status",
        "family_id",
        "practice_id",
        "failure_owner",
        "claim_scope",
        "changed_controls",
        "earliest_divergence",
        "hypotheses",
        "public_discriminator",
        "validation_delta",
        "predicted_observation",
        "decision_if_positive",
        "decision_if_negative",
        "protected_behavior",
        "compact",
        "detailed",
        "estimated_cost_usd",
        "deadline_feasible",
    }
    if not isinstance(candidate, dict):
        return ["candidate must be an object"]
    missing = sorted(required - set(candidate))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if candidate.get("version") != 1:
        errors.append("version must be 1")
    status = candidate.get("status")
    if status not in {"candidate", "no_extractable_control"}:
        errors.append("status must be candidate or no_extractable_control")
    if status == "no_extractable_control":
        return errors
    for field in (
        "family_id",
        "practice_id",
        "earliest_divergence",
        "public_discriminator",
        "validation_delta",
        "predicted_observation",
        "decision_if_positive",
        "decision_if_negative",
    ):
        if not _text(candidate.get(field)):
            errors.append(f"{field} must be non-empty")
    if candidate.get("failure_owner") not in FAILURE_OWNERS:
        errors.append("failure_owner is invalid")
    if candidate.get("claim_scope") not in CLAIM_SCOPES:
        errors.append("claim_scope is invalid")
    changed = candidate.get("changed_controls")
    if not isinstance(changed, list) or not changed or not all(_text(x) for x in changed):
        errors.append("changed_controls must be a non-empty string list")
    hypotheses = candidate.get("hypotheses")
    if (
        not isinstance(hypotheses, list)
        or not 1 <= len(hypotheses) <= 3
        or not all(_text(x) for x in hypotheses)
    ):
        errors.append("hypotheses must contain one to three strings")
    protected = candidate.get("protected_behavior")
    if not isinstance(protected, list) or not protected or not all(
        _text(x) for x in protected
    ):
        errors.append("protected_behavior must be a non-empty string list")
    compact = candidate.get("compact")
    if not isinstance(compact, dict):
        errors.append("compact must be an object")
    else:
        obligations = compact.get("obligations")
        if (
            not isinstance(obligations, list)
            or not 1 <= len(obligations) <= 3
            or not all(_text(x) for x in obligations)
        ):
            errors.append("compact.obligations must contain one to three strings")
        if not _text(compact.get("stop_rule")):
            errors.append("compact.stop_rule must be non-empty")
    detailed = candidate.get("detailed")
    if not isinstance(detailed, dict) or detailed.get("reviewer_only") is not True:
        errors.append("detailed must be reviewer-only")
    else:
        checks = detailed.get("prioritized_checks")
        if (
            not isinstance(checks, list)
            or not 1 <= len(checks) <= 5
            or not all(_text(x) for x in checks)
        ):
            errors.append("detailed.prioritized_checks must contain one to five strings")
    cost = candidate.get("estimated_cost_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        errors.append("estimated_cost_usd must be non-negative")
    if not isinstance(candidate.get("deadline_feasible"), bool):
        errors.append("deadline_feasible must be boolean")
    encoded = json.dumps(candidate, sort_keys=True).lower()
    for prohibited in (
        "hidden verifier",
        "expected answer",
        "known benchmark answer",
        "raw session",
    ):
        if prohibited in encoded:
            errors.append(f"prohibited evidence source: {prohibited}")
    return errors


def authorize_next_experiment(
    candidate: dict[str, Any],
    prior_discriminator_ids: set[str] | None = None,
) -> dict[str, Any]:
    errors = validate_practice_candidate(candidate)
    if errors:
        return {"authorized": False, "reason": "invalid_candidate", "errors": errors}
    if candidate["status"] == "no_extractable_control":
        return {"authorized": False, "reason": "no_extractable_control", "next": "park"}
    if candidate["failure_owner"] in NO_ROLLOUT_OWNERS:
        return {
            "authorized": False,
            "reason": "focused_fixture_required",
            "next": "focused_fixture_or_bounded_subagent",
        }
    if not candidate["deadline_feasible"]:
        return {"authorized": False, "reason": "deadline_infeasible", "next": "park"}
    discriminator_id = stable_identity(
        {
            "family_id": candidate["family_id"],
            "public_discriminator": candidate["public_discriminator"],
            "validation_delta": candidate["validation_delta"],
        }
    )
    if discriminator_id in (prior_discriminator_ids or set()):
        return {"authorized": False, "reason": "duplicate_discriminator", "next": "park"}
    if len(candidate["changed_controls"]) != 1:
        return {
            "authorized": True,
            "reason": "causal_isolation_required",
            "lane": "develop",
            "experiment": "adapted_control_isolation",
            "discriminator_id": discriminator_id,
        }
    scope = candidate["claim_scope"]
    experiment = {
        "task_boundary": "same_task_independent_evidence",
        "family_general": "untouched_same_family_transfer",
        "negative_transfer": "known_positive_sentinel",
    }[scope]
    return {
        "authorized": True,
        "reason": "new_decision_changing_information",
        "lane": "safety" if scope == "negative_transfer" else "develop",
        "experiment": experiment,
        "discriminator_id": discriminator_id,
    }


def record_lane_outcome(
    ledger: dict[str, Any],
    lane: str,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    if lane not in LANES:
        raise ValueError("lane is invalid")
    updated = json.loads(json.dumps(ledger))
    updated.setdefault("version", 1)
    updated.setdefault("outcomes", []).append(
        {"lane": lane, "outcome": outcome, "identity": stable_identity(outcome)}
    )
    return updated


def _reward(sample: dict[str, Any]) -> float:
    value = sample.get("raw_reward")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
