from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)


RECEIPT_KIND = "tb3_prelaunch_route_check"
RECEIPT_VERSION = 1
RECEIPT_FIELDS = {
    "version",
    "kind",
    "job_name",
    "task",
    "agent_name",
    "agent_import_path",
    "instruction_sha256",
    "catalog_sha256",
    "activation_mode",
    "development_practice_id",
    "expected_practice_id",
    "selected",
    "selected_practice_id",
    "selected_family",
    "selected_admitted",
    "eligible_match_count",
    "decision",
    "reason",
    "receipt_sha256",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def build_prelaunch_route_receipt(
    *,
    dataset_path: str | Path,
    task: str,
    job_name: str,
    agent_name: str,
    agent_import_path: str,
    agent_kwargs: Sequence[str],
    expected_practice_id: str,
    catalog_path: str | Path,
) -> dict[str, Any]:
    expected = expected_practice_id.strip()
    if not expected:
        raise ValueError("expected practice id must be non-empty")
    if "statem_codex_thin_family" not in agent_import_path:
        raise ValueError("prelaunch route checks require a thin-family adapter")

    parsed_kwargs = _parse_agent_kwargs(agent_kwargs)
    activation_mode = parsed_kwargs.get("activation_mode")
    development_practice_id = parsed_kwargs.get("development_practice_id")
    runtime_catalog = parsed_kwargs.get("practice_catalog_path")
    if activation_mode != "active":
        raise ValueError("prelaunch route checks require activation_mode=active")
    if development_practice_id != expected:
        raise ValueError(
            "development_practice_id must equal the expected prelaunch practice"
        )

    catalog = Path(catalog_path).expanduser().resolve()
    if not catalog.is_file():
        raise ValueError(f"practice catalog does not exist: {catalog}")
    if runtime_catalog is None:
        raise ValueError("practice_catalog_path must be bound in agent kwargs")
    if Path(runtime_catalog).expanduser().resolve() != catalog:
        raise ValueError("runtime and prelaunch practice catalogs do not match")

    instruction_path = _resolve_instruction_path(dataset_path, task)
    instruction_bytes = instruction_path.read_bytes()
    instruction = instruction_bytes.decode("utf-8")
    selection = select_thin_family_practice(
        instruction,
        catalog,
        activation_mode="active",
    )
    selected_practice_id = selection.get("practice_id")
    admitted = selected_practice_id == expected
    reason = "exact_visible_route_match" if admitted else (
        "no_visible_route_match"
        if selected_practice_id is None
        else "visible_route_selected_different_practice"
    )
    receipt: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "kind": RECEIPT_KIND,
        "job_name": job_name,
        "task": task,
        "agent_name": agent_name,
        "agent_import_path": agent_import_path,
        "instruction_sha256": hashlib.sha256(instruction_bytes).hexdigest(),
        "catalog_sha256": selection["catalog_sha256"],
        "activation_mode": activation_mode,
        "development_practice_id": development_practice_id,
        "expected_practice_id": expected,
        "selected": bool(selection.get("selected")),
        "selected_practice_id": selected_practice_id,
        "selected_family": selection.get("family"),
        "selected_admitted": (
            bool(selection.get("admitted"))
            if selected_practice_id is not None
            else None
        ),
        "eligible_match_count": int(selection.get("eligible_match_count") or 0),
        "decision": "admit" if admitted else "reject",
        "reason": reason,
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    errors = validate_prelaunch_route_receipt(receipt)
    if errors:
        raise ValueError("invalid prelaunch route receipt: " + "; ".join(errors))
    return receipt


def validate_prelaunch_route_receipt(receipt: dict[str, Any]) -> list[str]:
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
        "agent_name",
        "agent_import_path",
        "instruction_sha256",
        "catalog_sha256",
        "activation_mode",
        "development_practice_id",
        "expected_practice_id",
        "decision",
        "reason",
        "receipt_sha256",
    ):
        if not isinstance(receipt[field], str) or not receipt[field]:
            errors.append(f"{field} must be a non-empty string")
    if receipt["activation_mode"] != "active":
        errors.append("activation_mode must be active")
    if receipt["development_practice_id"] != receipt["expected_practice_id"]:
        errors.append("development practice must match expected practice")
    if "statem_codex_thin_family" not in receipt["agent_import_path"]:
        errors.append("agent_import_path must identify a thin-family adapter")
    if receipt["decision"] not in {"admit", "reject"}:
        errors.append("decision must be admit or reject")
    if not isinstance(receipt["selected"], bool):
        errors.append("selected must be boolean")
    if receipt["selected_practice_id"] is not None and not isinstance(
        receipt["selected_practice_id"], str
    ):
        errors.append("selected_practice_id must be a string or null")
    if receipt["selected_family"] is not None and not isinstance(
        receipt["selected_family"], str
    ):
        errors.append("selected_family must be a string or null")
    if receipt["selected_admitted"] is not None and not isinstance(
        receipt["selected_admitted"], bool
    ):
        errors.append("selected_admitted must be boolean or null")
    if (
        not isinstance(receipt["eligible_match_count"], int)
        or isinstance(receipt["eligible_match_count"], bool)
        or receipt["eligible_match_count"] < 0
    ):
        errors.append("eligible_match_count must be a non-negative integer")
    for field in ("instruction_sha256", "catalog_sha256", "receipt_sha256"):
        value = receipt[field]
        if isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase SHA256")

    if receipt["selected"] is True:
        if not receipt["selected_practice_id"]:
            errors.append("selected practice must have a practice id")
        if not receipt["selected_family"]:
            errors.append("selected practice must have a family")
        if not isinstance(receipt["selected_admitted"], bool):
            errors.append("selected practice must have an admission value")
        if receipt["eligible_match_count"] < 1:
            errors.append("selected practice requires an eligible match")
    else:
        if receipt["selected_practice_id"] is not None:
            errors.append("unselected receipt cannot name a practice")
        if receipt["selected_family"] is not None:
            errors.append("unselected receipt cannot name a family")
        if receipt["selected_admitted"] is not None:
            errors.append("unselected receipt cannot carry admission status")
        if receipt["eligible_match_count"] != 0:
            errors.append("unselected receipt must have zero eligible matches")

    exact_match = (
        receipt["selected"] is True
        and receipt["selected_practice_id"] == receipt["expected_practice_id"]
        and receipt["development_practice_id"] == receipt["expected_practice_id"]
    )
    if (receipt["decision"] == "admit") != exact_match:
        errors.append("decision does not match the selected practice")
    expected_reason = (
        "exact_visible_route_match"
        if exact_match
        else "no_visible_route_match"
        if receipt["selected_practice_id"] is None
        else "visible_route_selected_different_practice"
    )
    if receipt["reason"] != expected_reason:
        errors.append("reason does not match the route decision")
    if receipt["receipt_sha256"] != _receipt_sha256(receipt):
        errors.append("receipt_sha256 mismatch")
    return errors


def write_prelaunch_route_receipt(
    receipt: dict[str, Any], path: str | Path
) -> Path:
    errors = validate_prelaunch_route_receipt(receipt)
    if errors:
        raise ValueError("invalid prelaunch route receipt: " + "; ".join(errors))
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def _parse_agent_kwargs(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"agent kwarg must be KEY=VALUE, got {value!r}")
        key, item = value.split("=", 1)
        key = key.strip()
        if not key or not item:
            raise ValueError(f"agent kwarg must be KEY=VALUE, got {value!r}")
        if key in parsed:
            raise ValueError(f"agent kwarg is duplicated: {key}")
        parsed[key] = item
    return parsed


def _resolve_instruction_path(dataset_path: str | Path, task: str) -> Path:
    root = Path(dataset_path).expanduser().resolve()
    task_name = task.rsplit("/", 1)[-1]
    if not task_name or task_name in {".", ".."}:
        raise ValueError(f"invalid task name: {task!r}")
    candidates = (
        root / task_name / "instruction.md",
        root / "tasks" / task_name / "instruction.md",
    )
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one visible instruction for {task!r}, found {len(matches)}"
        )
    return matches[0]


def _receipt_sha256(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
