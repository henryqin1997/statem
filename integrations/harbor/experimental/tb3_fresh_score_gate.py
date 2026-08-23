from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRIAGE_USE = "k1_triage_only_not_pass_rate_estimate"
ESTIMATE_USE = "final_matched_estimate"


def evaluate_score_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    if ledger.get("version") not in {2, 3, 4}:
        raise ValueError("score ledger must use version 2, 3, or 4")
    objective = _mapping(ledger.get("objective"), "objective")
    official_tasks = _positive_int(
        objective.get("official_task_count"), "objective.official_task_count"
    )
    trials_per_task = _positive_int(
        objective.get("trials_per_task"), "objective.trials_per_task"
    )
    official_trials = official_tasks * trials_per_task
    declared_trials = objective.get("target_additional_reward_over_370")
    target_delta = _positive_number(
        objective.get("target_delta"), "objective.target_delta"
    )
    required_gain = official_trials * target_delta / 100.0
    if not isinstance(declared_trials, (int, float)) or isinstance(
        declared_trials, bool
    ):
        raise ValueError("objective target reward must be numeric")
    if abs(float(declared_trials) - required_gain) > 1e-9:
        raise ValueError("objective target reward does not match task/trial count")

    contract = _mapping(ledger.get("eligibility_contract"), "eligibility_contract")
    allowed_direct = _string_set(
        contract.get("allowed_direct_agents"), "allowed_direct_agents"
    )
    allowed_statem = _string_set(
        contract.get("allowed_statem_agents"), "allowed_statem_agents"
    )
    pairs = ledger.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("score ledger pairs must be a list")

    seen_pairs: set[str] = set()
    seen_jobs: set[str] = set()
    triage: list[dict[str, Any]] = []
    estimate: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(pairs):
        if not isinstance(raw, dict):
            errors.append(f"pairs[{index}] must be an object")
            continue
        pair_id = _text(raw.get("pair_id"))
        if not pair_id or pair_id in seen_pairs:
            errors.append(f"pairs[{index}] has missing or duplicate pair_id")
            continue
        seen_pairs.add(pair_id)
        if raw.get("score_eligible") is not True:
            excluded.append({"pair_id": pair_id, "reason": "score_eligible_false"})
            continue
        pair_errors, summary = _validate_pair(
            raw,
            allowed_direct=allowed_direct,
            allowed_statem=allowed_statem,
            seen_jobs=seen_jobs,
        )
        if pair_errors:
            errors.extend(f"{pair_id}: {item}" for item in pair_errors)
            continue
        use = raw.get("use")
        if use == TRIAGE_USE:
            if summary["sample_count_per_agent"] != 1:
                errors.append(f"{pair_id}: triage pair must use exactly one sample")
                continue
            triage.append(summary)
        elif use == ESTIMATE_USE:
            if summary["sample_count_per_agent"] != trials_per_task:
                errors.append(
                    f"{pair_id}: final estimate pair must use {trials_per_task} samples"
                )
                continue
            estimate.append(summary)
        else:
            errors.append(f"{pair_id}: score-eligible pair has invalid use")

    if errors:
        raise ValueError("; ".join(errors))

    triage_direct = sum(item["direct_reward"] for item in triage)
    triage_statem = sum(item["statem_reward"] for item in triage)
    estimate_direct = sum(item["direct_reward"] for item in estimate)
    estimate_statem = sum(item["statem_reward"] for item in estimate)
    estimate_tasks = {item["task"] for item in estimate}
    estimate_trials = sum(item["sample_count_per_agent"] for item in estimate)
    complete_estimate = (
        len(estimate_tasks) == official_tasks and estimate_trials == official_trials
    )
    estimated_delta_pp = (
        100.0 * (estimate_statem - estimate_direct) / official_trials
        if complete_estimate
        else None
    )
    target_supported = bool(
        complete_estimate
        and estimate_statem - estimate_direct >= required_gain
        and estimated_delta_pp is not None
        and estimated_delta_pp >= target_delta
    )
    return {
        "version": 1,
        "kind": "tb3_fresh_score_gate",
        "valid": True,
        "triage_pair_count": len(triage),
        "triage_sample_count_per_agent": sum(
            item["sample_count_per_agent"] for item in triage
        ),
        "observed_triage_direct_reward": triage_direct,
        "observed_triage_statem_reward": triage_statem,
        "observed_triage_reward_delta": triage_statem - triage_direct,
        "estimated_pair_count": len(estimate),
        "estimated_task_count": len(estimate_tasks),
        "estimated_trial_count_per_agent": estimate_trials,
        "estimated_direct_reward": estimate_direct,
        "estimated_statem_reward": estimate_statem,
        "estimated_reward_delta": estimate_statem - estimate_direct,
        "estimated_score_delta_pp": estimated_delta_pp,
        "target_delta_pp": target_delta,
        "required_additional_reward": required_gain,
        "target_supported": target_supported,
        "excluded_pair_count": len(excluded),
        "excluded_pairs": excluded,
    }


def _validate_pair(
    pair: dict[str, Any],
    *,
    allowed_direct: set[str],
    allowed_statem: set[str],
    seen_jobs: set[str],
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    pair_id = _text(pair.get("pair_id"))
    task = _text(pair.get("task"))
    sample_count = pair.get("sample_count_per_agent")
    if not task:
        errors.append("task is required")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 1:
        errors.append("sample_count_per_agent must be a positive integer")
        sample_count = 0
    for field in (
        "model",
        "codex_version",
        "reasoning_effort",
        "platform_class",
        "frozen_control_commit",
    ):
        if not _text(pair.get(field)):
            errors.append(f"{field} is required")
    if pair.get("timeout_multiplier") != 1.0:
        errors.append("timeout_multiplier must be standard 1.0")
    if pair.get("environment_build_timeout_multiplier") != 1.0:
        errors.append("environment_build_timeout_multiplier must be standard 1.0")
    if pair.get("retry_policy") != "no_retries":
        errors.append("retry_policy must be no_retries")
    if pair.get("no_upload") is not True:
        errors.append("no_upload must be explicitly true")
    if pair.get("fresh_for_frozen_control") is not True:
        errors.append("fresh_for_frozen_control must be explicitly true")

    direct = pair.get("direct")
    statem = pair.get("statem")
    if not isinstance(direct, dict) or not isinstance(statem, dict):
        return [*errors, "direct and statem records are required"], {}
    direct_reward = _validate_result(
        direct,
        label="direct",
        sample_count=sample_count,
        allowed_agents=allowed_direct,
        seen_jobs=seen_jobs,
        require_handoff=False,
        errors=errors,
    )
    statem_reward = _validate_result(
        statem,
        label="statem",
        sample_count=sample_count,
        allowed_agents=allowed_statem,
        seen_jobs=seen_jobs,
        require_handoff=True,
        errors=errors,
    )
    if _text(direct.get("job")) == _text(statem.get("job")):
        errors.append("direct and statem jobs must be distinct")
    if _text(direct.get("agent")) == _text(statem.get("agent")):
        errors.append("direct and statem agents must be distinct")
    return errors, {
        "pair_id": pair_id,
        "task": task,
        "sample_count_per_agent": sample_count,
        "direct_reward": direct_reward,
        "statem_reward": statem_reward,
    }


def _validate_result(
    result: dict[str, Any],
    *,
    label: str,
    sample_count: int,
    allowed_agents: set[str],
    seen_jobs: set[str],
    require_handoff: bool,
    errors: list[str],
) -> float:
    job = _text(result.get("job"))
    agent = _text(result.get("agent"))
    if not job or job in seen_jobs:
        errors.append(f"{label}.job is missing or duplicated")
    else:
        seen_jobs.add(job)
    if agent not in allowed_agents:
        errors.append(f"{label}.agent is not allowed")
    reward = result.get("raw_reward")
    if (
        not isinstance(reward, (int, float))
        or isinstance(reward, bool)
        or not 0 <= float(reward) <= sample_count
    ):
        errors.append(f"{label}.raw_reward must be within sample count")
        reward = 0.0
    if result.get("reward_valid") is not True:
        errors.append(f"{label}.reward_valid must be true")
    if result.get("protocol_valid") is not True:
        errors.append(f"{label}.protocol_valid must be true")
    if result.get("atif_schema") != "ATIF-v1.5":
        errors.append(f"{label}.atif_schema must be ATIF-v1.5")
    if result.get("raw_session_paths") != 0:
        errors.append(f"{label}.raw_session_paths must be zero")
    if require_handoff and result.get("final_statem_state") != "handoff":
        errors.append("statem.final_statem_state must be handoff")
    if not isinstance(result.get("backup_files"), int) or result.get("backup_files", 0) < 1:
        errors.append(f"{label}.backup_files must be positive")
    if not isinstance(result.get("backup_bytes"), int) or result.get("backup_bytes", 0) < 1:
        errors.append(f"{label}.backup_bytes must be positive")
    if not SHA256_RE.fullmatch(_text(result.get("backup_tree_sha256"))):
        errors.append(f"{label}.backup_tree_sha256 must be a SHA-256")
    return float(reward)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a fresh TB3 score ledger.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-target", action="store_true")
    args = parser.parse_args(argv)
    try:
        value = yaml.safe_load(args.ledger.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("score ledger root must be an object")
        receipt = evaluate_score_ledger(value)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"tb3 fresh score gate: {exc}")
        return 1
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if args.require_target and not receipt["target_supported"]:
        return 2
    return 0


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _string_set(value: Any, field: str) -> set[str]:
    if not isinstance(value, list) or not value or not all(_text(item) for item in value):
        raise ValueError(f"{field} must be a non-empty string list")
    return {_text(item) for item in value}


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _positive_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be positive")
    return float(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
