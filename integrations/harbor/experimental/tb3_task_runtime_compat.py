from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Iterable


RECEIPT_KIND = "tb3_task_runtime_compat"
RECEIPT_VERSION = 1
RECEIPT_FIELDS = {
    "version",
    "kind",
    "job_name",
    "task",
    "task_config_sha256",
    "runtime_name",
    "runtime_version",
    "supported_artifact_fields",
    "declared_artifact_fields",
    "unsupported_artifact_fields",
    "artifact_entry_count",
    "decision",
    "reason",
    "receipt_sha256",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def build_task_runtime_compat_receipt(
    *,
    dataset_path: str | Path,
    task: str,
    job_name: str,
    runtime_name: str,
    runtime_version: str,
    supported_artifact_fields: Iterable[str],
) -> dict[str, Any]:
    task_config_path = _resolve_task_config_path(dataset_path, task)
    task_config_bytes = task_config_path.read_bytes()
    task_config = tomllib.loads(task_config_bytes.decode("utf-8"))
    artifacts = task_config.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("top-level artifacts must be a list")

    supported = _normalized_fields(supported_artifact_fields, "supported")
    declared: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if isinstance(artifact, str):
            declared.add("source")
            continue
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact entry {index} must be a string or table")
        fields = _normalized_fields(artifact.keys(), f"artifact entry {index}")
        if "source" not in fields:
            raise ValueError(f"artifact entry {index} must declare source")
        declared.update(fields)

    unsupported = sorted(declared - supported)
    admitted = not unsupported
    receipt: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "kind": RECEIPT_KIND,
        "job_name": _nonempty(job_name, "job name"),
        "task": _nonempty(task, "task"),
        "task_config_sha256": hashlib.sha256(task_config_bytes).hexdigest(),
        "runtime_name": _nonempty(runtime_name, "runtime name"),
        "runtime_version": _nonempty(runtime_version, "runtime version"),
        "supported_artifact_fields": sorted(supported),
        "declared_artifact_fields": sorted(declared),
        "unsupported_artifact_fields": unsupported,
        "artifact_entry_count": len(artifacts),
        "decision": "admit" if admitted else "reject",
        "reason": (
            "artifact_fields_supported"
            if admitted
            else "unsupported_artifact_declaration_fields"
        ),
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    errors = validate_task_runtime_compat_receipt(receipt)
    if errors:
        raise ValueError("invalid task runtime receipt: " + "; ".join(errors))
    return receipt


def validate_task_runtime_compat_receipt(receipt: dict[str, Any]) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    errors: list[str] = []
    unknown = sorted(set(receipt) - RECEIPT_FIELDS)
    missing = sorted(RECEIPT_FIELDS - set(receipt))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if errors:
        return errors

    if receipt["version"] != RECEIPT_VERSION:
        errors.append("unsupported receipt version")
    if receipt["kind"] != RECEIPT_KIND:
        errors.append("unexpected receipt kind")
    for field in (
        "job_name",
        "task",
        "task_config_sha256",
        "runtime_name",
        "runtime_version",
        "decision",
        "reason",
        "receipt_sha256",
    ):
        if not isinstance(receipt[field], str) or not receipt[field]:
            errors.append(f"{field} must be a non-empty string")
    for field in (
        "supported_artifact_fields",
        "declared_artifact_fields",
        "unsupported_artifact_fields",
    ):
        value = receipt[field]
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(set(value))
        ):
            errors.append(f"{field} must be sorted unique non-empty strings")
    count = receipt["artifact_entry_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append("artifact_entry_count must be a non-negative integer")
    if receipt["decision"] not in {"admit", "reject"}:
        errors.append("decision must be admit or reject")
    for field in ("task_config_sha256", "receipt_sha256"):
        value = receipt[field]
        if isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase SHA256")

    supported = receipt["supported_artifact_fields"]
    declared = receipt["declared_artifact_fields"]
    unsupported = receipt["unsupported_artifact_fields"]
    if all(isinstance(value, list) for value in (supported, declared, unsupported)):
        expected_unsupported = sorted(set(declared) - set(supported))
        if unsupported != expected_unsupported:
            errors.append("unsupported fields do not match declared minus supported")
        expected_decision = "admit" if not expected_unsupported else "reject"
        if receipt["decision"] != expected_decision:
            errors.append("decision does not match unsupported fields")
        expected_reason = (
            "artifact_fields_supported"
            if expected_decision == "admit"
            else "unsupported_artifact_declaration_fields"
        )
        if receipt["reason"] != expected_reason:
            errors.append("reason does not match unsupported fields")
    if receipt["receipt_sha256"] != _receipt_sha256(receipt):
        errors.append("receipt_sha256 mismatch")
    return errors


def write_task_runtime_compat_receipt(
    receipt: dict[str, Any], path: str | Path
) -> Path:
    errors = validate_task_runtime_compat_receipt(receipt)
    if errors:
        raise ValueError("invalid task runtime receipt: " + "; ".join(errors))
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _resolve_task_config_path(dataset_path: str | Path, task: str) -> Path:
    root = Path(dataset_path).expanduser().resolve()
    task_name = task.rsplit("/", 1)[-1]
    if not task_name or task_name in {".", ".."}:
        raise ValueError(f"invalid task name: {task!r}")
    candidates = [
        root / task_name / "task.toml",
        root / "tasks" / task_name / "task.toml",
    ]
    if root.name == task_name:
        candidates.append(root / "task.toml")
    matches = list(dict.fromkeys(path for path in candidates if path.is_file()))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one task config for {task!r}, found {len(matches)}"
        )
    return matches[0]


def _normalized_fields(values: Iterable[object], label: str) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} fields must be non-empty strings")
        normalized.add(value.strip())
    if label == "supported" and not normalized:
        raise ValueError("supported artifact fields must be non-empty")
    return normalized


def _nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value.strip()


def _receipt_sha256(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
