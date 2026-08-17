from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from statem.miniyaml import loads as _yaml_loads
except ImportError:  # Allow the public helper to be copied outside the StateM tree.
    import yaml

    _yaml_loads = yaml.safe_load


DEFAULT_RUNBOOK = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "terminal-bench-2.1-deepseek-server-readiness-subset.yaml"
)


def load_runbook(path: Path = DEFAULT_RUNBOOK) -> dict[str, Any]:
    value = _yaml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("server-readiness runbook must be a YAML object")
    if value.get("schema_version") != 1:
        raise ValueError("server-readiness runbook schema_version must be 1")
    if value.get("policy_version") != 9:
        raise ValueError("server-readiness runbook policy_version must be 9")
    if value.get("family") != "server_readiness":
        raise ValueError("server-readiness runbook has the wrong family")

    selection = value.get("selection")
    lens = value.get("lens")
    runtime = value.get("runtime")
    if not all(isinstance(item, dict) for item in (selection, lens, runtime)):
        raise ValueError("server-readiness runbook is missing structured sections")
    if lens.get("id") != "service_lifecycle_readiness":
        raise ValueError("server-readiness runbook has the wrong lens id")
    groups = selection.get("require_all_groups")
    if not isinstance(groups, list) or [item.get("name") for item in groups] != [
        "service",
        "public_client",
        "persistence",
    ]:
        raise ValueError("server-readiness runbook requires exactly three trigger groups")
    for group in groups:
        patterns = group.get("any_regex") if isinstance(group, dict) else None
        if not isinstance(patterns, list) or not patterns or not all(
            isinstance(pattern, str) and pattern for pattern in patterns
        ):
            raise ValueError("every server-readiness trigger group needs regex patterns")
        for pattern in patterns:
            re.compile(pattern, flags=re.IGNORECASE)
    return value


def select_review_lens(task_text: str, runbook: dict[str, Any]) -> dict[str, Any]:
    normalized = re.sub(r"[ \t]+", " ", task_text.lower())
    selection = runbook["selection"]
    selected = all(
        any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in group["any_regex"]
        )
        for group in selection["require_all_groups"]
    )
    if selected:
        lens = runbook["lens"]
        return {
            "version": runbook["policy_version"],
            "selected": True,
            "selection_basis": selection["selection_basis"],
            "applies_in_state": selection["applies_in_state"],
            "lens": {
                "id": lens["id"],
                "instruction": lens["instruction"],
                "receipt": {"required_fields": lens["receipt"]["required_fields"]},
            },
            "limits": lens["limits"],
        }
    non_match = runbook["non_match"]
    return {
        "version": runbook["policy_version"],
        "selected": False,
        "selection_basis": non_match["selection_basis"],
        "applies_in_state": non_match["applies_in_state"],
        "lens": None,
        "limits": non_match["limits"],
    }


def render_review_lens(selection: dict[str, Any], runbook: dict[str, Any]) -> str:
    if not selection.get("selected"):
        return ""
    binding_errors = _selection_binding_errors(selection, runbook)
    if binding_errors:
        raise ValueError("; ".join(binding_errors))
    lens = runbook["lens"]
    fields = ", ".join(lens["receipt"]["required_fields"])
    runtime = runbook["runtime"]
    return (
        "DeepSeek review adaptation (self_review only):\n"
        f"- {lens['id']}: {lens['instruction']}\n"
        "- Run only one bounded countercheck. Do not broaden the solve, invent "
        "an acceptance rule, or delay handoff after the deadline reserve begins.\n"
        f"- Record the bounded evidence receipt at {runtime['receipt_path']} with fields: "
        f"{fields}. Validate it with `python3 {runtime['validator_path']} "
        f"validate --selection {runtime['selection_path']} --receipt "
        f"{runtime['receipt_path']}`. A pending or failed receipt is a concrete issue, "
        "not a clean handoff."
    )


def receipt_template(
    selection: dict[str, Any], runbook: dict[str, Any]
) -> dict[str, Any] | None:
    lens = selection.get("lens")
    if not selection.get("selected") or not isinstance(lens, dict):
        return None
    binding_errors = _selection_binding_errors(selection, runbook)
    if binding_errors:
        raise ValueError("; ".join(binding_errors))
    lens = runbook["lens"]
    payload: dict[str, Any] = {
        "version": selection["version"],
        "lens_id": lens["id"],
        "status": "pending",
    }
    for field in lens["receipt"]["required_fields"]:
        payload.setdefault(field, None)
    return payload


def _selection_binding_errors(
    selection: dict[str, Any], runbook: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_selection = runbook["selection"]
    expected_lens = runbook["lens"]
    if selection.get("version") != runbook["policy_version"]:
        errors.append("selection version does not match runbook")
    if selection.get("selection_basis") != expected_selection["selection_basis"]:
        errors.append("selection basis does not match runbook")
    if selection.get("applies_in_state") != expected_selection["applies_in_state"]:
        errors.append("selection state does not match runbook")
    if selection.get("limits") != expected_lens["limits"]:
        errors.append("selection limits do not match runbook")

    lens = selection.get("lens")
    if not isinstance(lens, dict) or lens.get("id") != expected_lens["id"]:
        errors.append("selection is not bound to the server-readiness lens")
        return errors
    if lens.get("instruction") != expected_lens["instruction"]:
        errors.append("selection instruction does not match runbook")
    contract = lens.get("receipt")
    if not isinstance(contract, dict) or contract.get(
        "required_fields"
    ) != expected_lens["receipt"]["required_fields"]:
        errors.append("selection receipt fields do not match runbook")
    return errors


def validate_receipt(
    selection: dict[str, Any], receipt: dict[str, Any], runbook: dict[str, Any]
) -> list[str]:
    lens = selection.get("lens")
    if not selection.get("selected") or not isinstance(lens, dict):
        return ["selection does not require a DeepSeek contract receipt"]
    binding_errors = _selection_binding_errors(selection, runbook)
    if binding_errors:
        return binding_errors

    errors: list[str] = []
    if receipt.get("lens_id") != lens["id"]:
        errors.append("receipt lens_id does not match selection")
    required_values = runbook["lens"]["receipt"]["required_values"]
    if receipt.get("status") != required_values["status"]:
        errors.append("receipt status must be passed")
    for field in runbook["lens"]["receipt"]["required_fields"]:
        value = receipt.get(field)
        if value is None or value == "" or value == [] or value == {}:
            errors.append(f"missing receipt field: {field}")
    if (
        receipt.get("detached_from_agent_session")
        is not required_values["detached_from_agent_session"]
    ):
        errors.append("service is not detached from the agent session")
    return errors


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the public server-readiness subset.")
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK)
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--task-text", type=Path, required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--selection", type=Path, required=True)
    validate_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        runbook = load_runbook(args.runbook)
        if args.command == "select":
            result = select_review_lens(
                args.task_text.read_text(encoding="utf-8"), runbook
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        selection = _read_json(args.selection)
        receipt = _read_json(args.receipt)
        errors = validate_receipt(selection, receipt, runbook)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(json.dumps({"status": "failed", "errors": [str(exc)]}))
        return 2
    status = "passed" if not errors else "failed"
    print(json.dumps({"status": status, "errors": errors}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
