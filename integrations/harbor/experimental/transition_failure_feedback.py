from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


SHA256_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b")
MAX_FAILED_CHECKS = 4
MAX_SUMMARY_CHARS = 500
MAX_UNCHANGED_GATE_ATTEMPTS = 2


def latest_transition_feedback(state: dict[str, Any]) -> dict[str, Any] | None:
    current = _text(state.get("current"))
    entry_id = _text(state.get("current_entry_id"))
    history = state.get("history")
    if not current or not entry_id or not isinstance(history, list):
        raise ValueError("state requires current, current_entry_id, and history")

    blocked_transitions: list[dict[str, Any]] = []
    for event in history:
        if not isinstance(event, dict) or event.get("event") != "goto_blocked":
            continue
        if _text(event.get("from")) != current:
            continue
        if _text(event.get("current_entry_id")) != entry_id:
            continue
        failed: list[dict[str, Any]] = []
        for result in event.get("results") or []:
            if (
                not isinstance(result, dict)
                or result.get("passed") is not False
                or result.get("blocking") is not True
            ):
                continue
            summary = _bounded_summary(result.get("output"))
            failed.append(
                {
                    "type": _text(result.get("type")),
                    "purpose": _text(result.get("purpose")),
                    "exit_code": result.get("exit_code"),
                    "on_failure": _text(result.get("on_failure")),
                    "summary": summary,
                    **_repair_ownership(summary),
                }
            )
            if len(failed) >= MAX_FAILED_CHECKS:
                break
        if failed:
            blocked_transitions.append(
                {
                    "current_state": current,
                    "entry_id": entry_id,
                    "target_state": _text(event.get("to")),
                    "stage": _text(event.get("stage")),
                    "failed_checks": failed,
                }
            )
    if not blocked_transitions:
        return None

    latest = blocked_transitions[-1]
    blocker_fingerprint = stable_sha256(latest)
    repeat_count = sum(
        stable_sha256(candidate) == blocker_fingerprint
        for candidate in blocked_transitions
    )

    return {
        "version": 1,
        "kind": "transition_failure_feedback",
        **latest,
        "blocker_fingerprint": blocker_fingerprint,
        "repeat_count": repeat_count,
        "repair_budget_exhausted": repeat_count > MAX_UNCHANGED_GATE_ATTEMPTS,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize bounded feedback for the latest blocked StateM transition."
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.unlink(missing_ok=True)
    try:
        value = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state root must be an object")
        receipt = latest_transition_feedback(value)
        if receipt is None:
            print(json.dumps({"present": False}, sort_keys=True))
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"transition failure feedback: {exc}")
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _bounded_summary(value: Any) -> str:
    first_line = _text(value).splitlines()[:1]
    summary = first_line[0] if first_line else "blocked transition check failed"
    summary = SHA256_RE.sub("<sha256>", summary)
    summary = UUID_RE.sub("<uuid>", summary)
    return summary[:MAX_SUMMARY_CHARS]


def _repair_ownership(summary: str) -> dict[str, str]:
    lowered = summary.lower()
    if "failure feedback gate" in lowered and "validation delta" in lowered:
        return {
            "failure_class": "acceptance_plan_gap",
            "repair_owner": "test_planner",
            "repair_action": (
                "Read retry-brief.json, append its exact validation_delta."
                "discriminating_check to one candidate-blind required_strata list, "
                "regenerate preflight evidence, and rerun only the failed gate."
            ),
        }
    if "preflight" in lowered or "candidate-blind" in lowered:
        return {
            "failure_class": "acceptance_plan_gap",
            "repair_owner": "test_planner",
            "repair_action": (
                "Repair the candidate-blind plan or its public evidence binding, "
                "preserve passing obligations, and rerun only the failed gate."
            ),
        }
    return {
        "failure_class": "unclassified_transition_gate",
        "repair_owner": "transition_check_owner",
        "repair_action": (
            "Inspect the bounded failed gate, repair its owning public artifact or "
            "receipt without weakening it, and rerun only that transition."
        ),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
