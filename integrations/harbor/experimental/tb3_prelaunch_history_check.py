from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


INDEX_KIND = "tb3_prelaunch_history_index"
INDEX_VERSION = 1
RECEIPT_KIND = "tb3_prelaunch_history_check"
RECEIPT_VERSION = 1
EVIDENCE_CLASSES = {
    "adapted",
    "fresh_direct",
    "infrastructure_replacement",
    "repeated_calibration",
    "sentinel",
}
INDEX_FIELDS = {
    "version",
    "kind",
    "source_root_count",
    "job_name_prefixes",
    "records",
    "index_sha256",
}
RECORD_FIELDS = {
    "job_name",
    "trial_id",
    "task",
    "agent_name",
    "model",
    "codex_version",
    "reward",
    "reward_valid",
    "protocol_valid",
    "result_sha256",
}


def build_history_index(
    roots: Iterable[str | Path],
    *,
    job_name_prefixes: Iterable[str] = (),
) -> dict[str, Any]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    root_count = 0
    prefixes = tuple(sorted(set(job_name_prefixes)))
    if any(not isinstance(prefix, str) or not prefix for prefix in prefixes):
        raise ValueError("history job prefixes must be non-empty strings")
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"history root does not exist: {root}")
        root_count += 1
        for job_dir in _job_directories(root):
            if prefixes and not job_dir.name.startswith(prefixes):
                continue
            for result_path in sorted(job_dir.glob("*/result.json")):
                record = _record_from_result(job_dir, result_path)
                if record is None:
                    continue
                records[(record["job_name"], record["trial_id"])] = record
    ordered = sorted(
        records.values(),
        key=lambda item: (item["task"], item["job_name"], item["trial_id"]),
    )
    index: dict[str, Any] = {
        "version": INDEX_VERSION,
        "kind": INDEX_KIND,
        "source_root_count": root_count,
        "job_name_prefixes": list(prefixes),
        "records": ordered,
    }
    index["index_sha256"] = _payload_sha256(index, "index_sha256")
    errors = validate_history_index(index)
    if errors:
        raise ValueError("invalid history index: " + "; ".join(errors))
    return index


def build_history_receipt(
    *,
    index: dict[str, Any],
    task: str,
    job_name: str,
    agent_name: str,
    model: str,
    codex_version: str,
    evidence_class: str,
    boundary_change_reason: str | None = None,
) -> dict[str, Any]:
    errors = validate_history_index(index)
    if errors:
        raise ValueError("invalid history index: " + "; ".join(errors))
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError("unsupported prelaunch evidence class")
    required_strings = {
        "task": task,
        "job_name": job_name,
        "agent_name": agent_name,
        "model": model,
        "codex_version": codex_version,
    }
    for label, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")

    matches = [
        record
        for record in index["records"]
        if record["task"] == task
        and record["agent_name"] == agent_name
        and record["model"] == model
        and record["job_name"] != job_name
    ]
    valid_matches = [
        record
        for record in matches
        if record["reward_valid"] and record["protocol_valid"]
    ]
    exact_agent_matches = [
        record
        for record in valid_matches
        if record["codex_version"] == codex_version
    ]
    reason = "no_compatible_history"
    decision = "admit"
    score_eligible = evidence_class == "fresh_direct"

    if evidence_class == "fresh_direct" and valid_matches:
        decision = "reject"
        reason = "prior_reward_valid_direct_observation"
        score_eligible = False
    elif evidence_class == "adapted" and exact_agent_matches:
        decision = "reject"
        reason = "duplicate_adapted_generation"
        score_eligible = False
    elif evidence_class == "infrastructure_replacement":
        score_eligible = not valid_matches
        if valid_matches:
            decision = "reject"
            reason = "replacement_has_prior_reward_valid_observation"
        elif not boundary_change_reason or not boundary_change_reason.strip():
            decision = "reject"
            reason = "replacement_missing_boundary_change"
        else:
            reason = "invalid_prior_with_declared_boundary_change"
    elif evidence_class in {"repeated_calibration", "sentinel"}:
        score_eligible = False
        reason = "explicit_non_score_repeat"

    receipt: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "kind": RECEIPT_KIND,
        "index_sha256": index["index_sha256"],
        "task": task,
        "job_name": job_name,
        "agent_name": agent_name,
        "model": model,
        "codex_version": codex_version,
        "evidence_class": evidence_class,
        "boundary_change_reason": boundary_change_reason,
        "compatible_history_count": len(matches),
        "valid_history_count": len(valid_matches),
        "matching_history": [
            {
                key: record[key]
                for key in (
                    "job_name",
                    "trial_id",
                    "codex_version",
                    "reward",
                    "reward_valid",
                    "protocol_valid",
                    "result_sha256",
                )
            }
            for record in valid_matches
        ],
        "decision": decision,
        "reason": reason,
        "score_eligible": score_eligible,
    }
    receipt["receipt_sha256"] = _payload_sha256(receipt, "receipt_sha256")
    errors = validate_history_receipt(receipt)
    if errors:
        raise ValueError("invalid history receipt: " + "; ".join(errors))
    return receipt


def validate_history_index(index: dict[str, Any]) -> list[str]:
    if not isinstance(index, dict):
        return ["history index must be an object"]
    errors: list[str] = []
    unknown = sorted(set(index) - INDEX_FIELDS)
    missing = sorted(INDEX_FIELDS - set(index))
    if unknown:
        errors.append("unknown index fields: " + ", ".join(unknown))
    if missing:
        errors.append("missing index fields: " + ", ".join(missing))
    if errors:
        return errors
    if index.get("version") != INDEX_VERSION:
        errors.append("unsupported history index version")
    if index.get("kind") != INDEX_KIND:
        errors.append("unexpected history index kind")
    if not isinstance(index.get("source_root_count"), int):
        errors.append("source_root_count must be an integer")
    prefixes = index.get("job_name_prefixes")
    if not isinstance(prefixes, list) or any(
        not isinstance(prefix, str) or not prefix for prefix in prefixes
    ):
        errors.append("job_name_prefixes must be a string list")
    records = index.get("records")
    if not isinstance(records, list):
        errors.append("records must be a list")
    else:
        identities: set[tuple[str, str]] = set()
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"records[{position}] must be an object")
                continue
            unknown_record = sorted(set(record) - RECORD_FIELDS)
            missing_record = sorted(RECORD_FIELDS - set(record))
            if unknown_record:
                errors.append(
                    f"records[{position}] has unknown fields: "
                    + ", ".join(unknown_record)
                )
            if missing_record:
                errors.append(
                    f"records[{position}] has missing fields: "
                    + ", ".join(missing_record)
                )
                continue
            identity = (record.get("job_name"), record.get("trial_id"))
            if identity in identities:
                errors.append(f"records[{position}] duplicates a trial identity")
            identities.add(identity)
            for field in (
                "job_name",
                "trial_id",
                "task",
                "agent_name",
                "model",
                "codex_version",
                "result_sha256",
            ):
                if not isinstance(record.get(field), str) or not record[field]:
                    errors.append(f"records[{position}].{field} must be non-empty")
            for field in ("reward_valid", "protocol_valid"):
                if not isinstance(record.get(field), bool):
                    errors.append(f"records[{position}].{field} must be boolean")
    digest = index.get("index_sha256")
    if not isinstance(digest, str) or digest != _payload_sha256(index, "index_sha256"):
        errors.append("index_sha256 mismatch")
    return errors


def validate_history_receipt(receipt: dict[str, Any]) -> list[str]:
    required = {
        "version",
        "kind",
        "index_sha256",
        "task",
        "job_name",
        "agent_name",
        "model",
        "codex_version",
        "evidence_class",
        "boundary_change_reason",
        "compatible_history_count",
        "valid_history_count",
        "matching_history",
        "decision",
        "reason",
        "score_eligible",
        "receipt_sha256",
    }
    if not isinstance(receipt, dict):
        return ["history receipt must be an object"]
    errors: list[str] = []
    unknown = sorted(set(receipt) - required)
    missing = sorted(required - set(receipt))
    if unknown:
        errors.append("unknown receipt fields: " + ", ".join(unknown))
    if missing:
        errors.append("missing receipt fields: " + ", ".join(missing))
    if errors:
        return errors
    if receipt["version"] != RECEIPT_VERSION or receipt["kind"] != RECEIPT_KIND:
        errors.append("unsupported history receipt identity")
    if receipt["evidence_class"] not in EVIDENCE_CLASSES:
        errors.append("unsupported receipt evidence class")
    if receipt["decision"] not in {"admit", "reject"}:
        errors.append("receipt decision must be admit or reject")
    if not isinstance(receipt["score_eligible"], bool):
        errors.append("receipt score_eligible must be boolean")
    for field in ("compatible_history_count", "valid_history_count"):
        if not isinstance(receipt[field], int) or receipt[field] < 0:
            errors.append(f"{field} must be a non-negative integer")
    if not isinstance(receipt["matching_history"], list):
        errors.append("matching_history must be a list")
    if receipt["receipt_sha256"] != _payload_sha256(receipt, "receipt_sha256"):
        errors.append("receipt_sha256 mismatch")
    return errors


def write_json_receipt(payload: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _job_directories(root: Path) -> list[Path]:
    if (root / "result.json").is_file():
        return [root]
    return sorted(path for path in root.iterdir() if path.is_dir())


def _record_from_result(job_dir: Path, result_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    agent = payload.get("agent_info") or {}
    model = agent.get("model_info") or {}
    verifier = payload.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")
    reward_valid = isinstance(reward, (int, float)) and not isinstance(reward, bool)
    protocol_valid = payload.get("exception_info") is None and reward_valid
    trial_id = str(payload.get("id") or result_path.parent.name)
    task = payload.get("task_name") or payload.get("task_id")
    required = {
        "task": task,
        "agent_name": agent.get("name"),
        "model": model.get("name"),
        "codex_version": agent.get("version"),
    }
    if any(not isinstance(value, str) or not value for value in required.values()):
        return None
    return {
        "job_name": job_dir.name,
        "trial_id": trial_id,
        **required,
        "reward": reward if reward_valid else None,
        "reward_valid": reward_valid,
        "protocol_valid": protocol_valid,
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    }


def _payload_sha256(payload: dict[str, Any], digest_field: str) -> str:
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key != digest_field},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
