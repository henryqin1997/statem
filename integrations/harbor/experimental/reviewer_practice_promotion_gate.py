from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from integrations.harbor.experimental.artifact_identity import stable_sha256
from integrations.harbor.experimental.multirole_promotion_gate import _read_yaml


_GENERIC_FIELDS = (
    "practice_id",
    "trigger",
    "procedure",
    "required_evidence",
    "abstention_conditions",
    "known_failure_modes",
)
_CANDIDATE_FIELDS = {
    "version",
    "kind",
    *_GENERIC_FIELDS,
    "development_evidence",
    "holdout_evidence",
    "sentinel_evidence",
}
_DEVELOPMENT_FIELDS = {
    "task_id",
    "task_family",
    "mechanism_fingerprint",
    "mechanism_observed",
    "reward_valid",
    "protocol_valid",
    "public_evidence_only",
    "raw_reward",
    "cost_usd",
    "wall_seconds",
    "evidence_sha256",
}
_EVALUATION_FIELDS = {
    "task_id",
    "task_family",
    "frozen_practice_sha256",
    "reward_before",
    "reward_after",
    "reward_valid",
    "protocol_valid",
    "public_evidence_only",
    "cost_usd_before",
    "cost_usd_after",
    "wall_seconds_before",
    "wall_seconds_after",
    "evidence_sha256",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sha256(value: Any) -> bool:
    text = _text(value)
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _validate_policy(policy: dict[str, Any]) -> dict[str, int]:
    if policy.get("version") != 1 or policy.get("kind") != "reviewer_practice_promotion_policy":
        raise ValueError("promotion policy must be reviewer_practice_promotion_policy v1")
    requirements = policy.get("candidate_requirements")
    if not isinstance(requirements, dict):
        raise ValueError("promotion policy requires candidate_requirements")
    required = {
        "distinct_development_tasks",
        "distinct_task_families",
        "fresh_holdout_tasks_after_freeze",
        "unchanged_sentinel_tasks",
    }
    if set(requirements) != required or any(
        not isinstance(requirements[key], int) or requirements[key] < 1
        for key in required
    ):
        raise ValueError("promotion candidate requirements must be positive integers")
    return requirements


def _validate_candidate(candidate: dict[str, Any]) -> None:
    if set(candidate) != _CANDIDATE_FIELDS:
        raise ValueError("reviewer practice candidate has unexpected or missing fields")
    if candidate.get("version") != 1 or candidate.get("kind") != "reviewer_practice_candidate":
        raise ValueError("reviewer practice candidate must be v1")
    for field in _GENERIC_FIELDS[:4]:
        if not _text(candidate.get(field)):
            raise ValueError(f"reviewer practice candidate requires {field}")
    for field in _GENERIC_FIELDS[4:]:
        if not _string_list(candidate.get(field)):
            raise ValueError(f"reviewer practice candidate requires non-empty {field}")
    for field in ("development_evidence", "holdout_evidence", "sentinel_evidence"):
        if not isinstance(candidate.get(field), list):
            raise ValueError(f"reviewer practice candidate requires list {field}")


def _validate_development(record: dict[str, Any]) -> None:
    if set(record) != _DEVELOPMENT_FIELDS:
        raise ValueError("development evidence has unexpected or missing fields")
    if not _text(record.get("task_id")) or not _text(record.get("task_family")):
        raise ValueError("development evidence requires task and family identities")
    if not _sha256(record.get("mechanism_fingerprint")) or not _sha256(
        record.get("evidence_sha256")
    ):
        raise ValueError("development evidence requires sha256 identities")
    for field in (
        "mechanism_observed",
        "reward_valid",
        "protocol_valid",
        "public_evidence_only",
    ):
        if not isinstance(record.get(field), bool):
            raise ValueError(f"development evidence requires boolean {field}")
    for field in ("raw_reward", "cost_usd", "wall_seconds"):
        if not _number(record.get(field)) or record[field] < 0:
            raise ValueError(f"development evidence requires non-negative {field}")


def _validate_evaluation(record: dict[str, Any], *, sentinel: bool) -> None:
    expected = set(_EVALUATION_FIELDS)
    expected.add("unchanged_sentinel" if sentinel else "fresh_after_freeze")
    if set(record) != expected:
        kind = "sentinel" if sentinel else "holdout"
        raise ValueError(f"{kind} evidence has unexpected or missing fields")
    if not _text(record.get("task_id")) or not _text(record.get("task_family")):
        raise ValueError("evaluation evidence requires task and family identities")
    if not _sha256(record.get("frozen_practice_sha256")) or not _sha256(
        record.get("evidence_sha256")
    ):
        raise ValueError("evaluation evidence requires sha256 identities")
    boolean_fields = (
        "reward_valid",
        "protocol_valid",
        "public_evidence_only",
        "unchanged_sentinel" if sentinel else "fresh_after_freeze",
    )
    for field in boolean_fields:
        if not isinstance(record.get(field), bool):
            raise ValueError(f"evaluation evidence requires boolean {field}")
    for field in (
        "reward_before",
        "reward_after",
        "cost_usd_before",
        "cost_usd_after",
        "wall_seconds_before",
        "wall_seconds_after",
    ):
        if not _number(record.get(field)) or record[field] < 0:
            raise ValueError(f"evaluation evidence requires non-negative {field}")


def _practice_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in _GENERIC_FIELDS}


def evaluate_candidate(
    *, candidate: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    requirements = _validate_policy(policy)
    _validate_candidate(candidate)
    development = candidate["development_evidence"]
    holdouts = candidate["holdout_evidence"]
    sentinels = candidate["sentinel_evidence"]
    for record in development:
        if not isinstance(record, dict):
            raise ValueError("development evidence items must be objects")
        _validate_development(record)
    for record in holdouts:
        if not isinstance(record, dict):
            raise ValueError("holdout evidence items must be objects")
        _validate_evaluation(record, sentinel=False)
    for record in sentinels:
        if not isinstance(record, dict):
            raise ValueError("sentinel evidence items must be objects")
        _validate_evaluation(record, sentinel=True)

    practice_sha256 = stable_sha256(_practice_payload(candidate))
    reject_reasons: list[str] = []
    quarantine_reasons: list[str] = []
    task_ids = {
        record["task_id"] for record in [*development, *holdouts, *sentinels]
    }
    generic_text = "\n".join(
        [
            candidate["trigger"],
            candidate["procedure"],
            candidate["required_evidence"],
            *candidate["abstention_conditions"],
            *candidate["known_failure_modes"],
        ]
    ).lower()
    if "terminal-bench/" in generic_text or any(
        task_id.lower() in generic_text for task_id in task_ids
    ):
        reject_reasons.append("generic practice text contains a task identifier")
    if any(
        not record["public_evidence_only"]
        for record in [*development, *holdouts, *sentinels]
    ):
        reject_reasons.append("candidate relies on non-public evidence")

    valid_development = [
        record
        for record in development
        if record["mechanism_observed"]
        and record["reward_valid"]
        and record["protocol_valid"]
    ]
    valid_task_ids = {record["task_id"] for record in valid_development}
    valid_families = {record["task_family"] for record in valid_development}
    mechanism_ids = {
        record["mechanism_fingerprint"] for record in valid_development
    }
    if len(valid_task_ids) < requirements["distinct_development_tasks"]:
        quarantine_reasons.append("insufficient valid development tasks")
    if len(valid_families) < requirements["distinct_task_families"]:
        quarantine_reasons.append("insufficient distinct development task families")
    if len(mechanism_ids) != 1:
        quarantine_reasons.append("development evidence does not bind one shared mechanism")

    valid_holdouts = [
        record
        for record in holdouts
        if record["fresh_after_freeze"]
        and record["reward_valid"]
        and record["protocol_valid"]
        and record["frozen_practice_sha256"] == practice_sha256
        and record["reward_after"] >= record["reward_before"]
        and record["task_id"] not in valid_task_ids
    ]
    if len({record["task_id"] for record in valid_holdouts}) < requirements[
        "fresh_holdout_tasks_after_freeze"
    ]:
        quarantine_reasons.append("missing fresh non-regressing holdout evidence")

    holdout_task_ids = {record["task_id"] for record in valid_holdouts}
    valid_sentinels = [
        record
        for record in sentinels
        if record["unchanged_sentinel"]
        and record["reward_valid"]
        and record["protocol_valid"]
        and record["frozen_practice_sha256"] == practice_sha256
        and record["reward_after"] >= record["reward_before"]
        and record["task_id"] not in valid_task_ids | holdout_task_ids
    ]
    if len({record["task_id"] for record in valid_sentinels}) < requirements[
        "unchanged_sentinel_tasks"
    ]:
        quarantine_reasons.append("missing unchanged non-regressing sentinel evidence")

    decision = "reject" if reject_reasons else "quarantine" if quarantine_reasons else "promote"
    return {
        "version": 1,
        "kind": "reviewer_practice_promotion_decision",
        "practice_id": candidate["practice_id"],
        "practice_sha256": practice_sha256,
        "candidate_sha256": stable_sha256(candidate),
        "policy_sha256": stable_sha256(policy),
        "decision": decision,
        "reject_reasons": reject_reasons,
        "quarantine_reasons": quarantine_reasons,
        "evidence_counts": {
            "valid_development_tasks": len(valid_task_ids),
            "valid_development_families": len(valid_families),
            "valid_holdout_tasks": len({record["task_id"] for record in valid_holdouts}),
            "valid_sentinel_tasks": len({record["task_id"] for record in valid_sentinels}),
        },
        "reporting": {
            "raw_reward": True,
            "protocol_validity": True,
            "cost": True,
            "wall_time": True,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    policy = _read_yaml(args.policy)
    decision = evaluate_candidate(candidate=candidate, policy=policy)
    _write_json(args.output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
