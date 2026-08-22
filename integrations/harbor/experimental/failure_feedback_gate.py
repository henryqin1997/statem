from __future__ import annotations

import argparse
import copy
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from .artifact_identity import stable_sha256
except ImportError:
    from artifact_identity import stable_sha256  # type: ignore[no-redef]


DEFAULT_DECISION = Path("/tmp/statem-verification-checks/recovering-develop/replay-decision.json")
DEFAULT_BRIEF = Path("/tmp/statem-verification-checks/recovering-develop/retry-brief.json")
DEFAULT_PREFLIGHT = Path("/tmp/statem-verification-checks/multirole/preflight-evidence.json")
DEFAULT_VALIDATION = Path("/tmp/statem-verification-checks/recovering-develop/validation-delta-receipt.json")
DEFAULT_REPAIR_DRAFT = Path(
    "/tmp/statem-verification-checks/recovering-develop/"
    "preflight-evidence-repair-draft.json"
)
DEFAULT_RAW_PREFLIGHT = Path(
    "/tmp/statem-verification-checks/recovering-develop/preflight-evidence.raw.json"
)
DEFAULT_REPAIR_RECEIPT = Path(
    "/tmp/statem-verification-checks/recovering-develop/"
    "preflight-repair-transaction.json"
)
DEFAULT_TRANSITION_FEEDBACK = Path(
    "/tmp/statem-verification-checks/recovering-develop/"
    "transition-failure-feedback.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carry a host-validated failure and validation delta into the next candidate-blind plan."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    prepare.add_argument("--output", type=Path, default=DEFAULT_BRIEF)
    validate = sub.add_parser("validate-preflight")
    validate.add_argument("--brief", type=Path, default=DEFAULT_BRIEF)
    validate.add_argument("--preflight-evidence", type=Path, default=DEFAULT_PREFLIGHT)
    validate.add_argument("--output", type=Path, default=DEFAULT_VALIDATION)
    commit = sub.add_parser("commit-preflight-repair")
    commit.add_argument("--brief", type=Path, default=DEFAULT_BRIEF)
    commit.add_argument("--canonical-preflight", type=Path, default=DEFAULT_PREFLIGHT)
    commit.add_argument("--repair-draft", type=Path, default=DEFAULT_REPAIR_DRAFT)
    commit.add_argument("--raw-backup", type=Path, default=DEFAULT_RAW_PREFLIGHT)
    commit.add_argument(
        "--transition-feedback", type=Path, default=DEFAULT_TRANSITION_FEEDBACK
    )
    commit.add_argument("--output", type=Path, default=DEFAULT_REPAIR_RECEIPT)
    targeted = sub.add_parser("commit-targeted-preflight-repair")
    targeted.add_argument("--brief", type=Path, default=DEFAULT_BRIEF)
    targeted.add_argument(
        "--canonical-preflight", type=Path, default=DEFAULT_PREFLIGHT
    )
    targeted.add_argument("--raw-backup", type=Path, default=DEFAULT_RAW_PREFLIGHT)
    targeted.add_argument(
        "--transition-feedback", type=Path, default=DEFAULT_TRANSITION_FEEDBACK
    )
    targeted.add_argument("--output", type=Path, default=DEFAULT_REPAIR_RECEIPT)
    args = parser.parse_args(argv)
    if args.action in {
        "validate-preflight",
        "commit-preflight-repair",
        "commit-targeted-preflight-repair",
    }:
        # A failed validation must not leave an earlier cycle's success receipt
        # available to progress or audit consumers.
        args.output.unlink(missing_ok=True)
    try:
        if args.action == "prepare":
            receipt = prepare_retry_brief(
                _read_json(args.decision) if args.decision.is_file() else None
            )
        elif args.action == "validate-preflight":
            receipt = validate_preflight_delta(
                brief=_read_json(args.brief),
                preflight_evidence=_read_json(args.preflight_evidence),
            )
            _write_json_atomic(args.output, receipt)
        elif args.action == "commit-preflight-repair":
            receipt = commit_preflight_repair(
                brief_path=args.brief,
                canonical_path=args.canonical_preflight,
                draft_path=args.repair_draft,
                raw_backup_path=args.raw_backup,
                transition_feedback_path=args.transition_feedback,
                receipt_path=args.output,
            )
        else:
            receipt = commit_targeted_preflight_repair(
                brief_path=args.brief,
                canonical_path=args.canonical_preflight,
                raw_backup_path=args.raw_backup,
                transition_feedback_path=args.transition_feedback,
                receipt_path=args.output,
            )
        if args.action == "prepare":
            _write_json_atomic(args.output, receipt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"failure feedback gate: {exc}")
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def prepare_retry_brief(decision: dict[str, Any] | None) -> dict[str, Any]:
    if decision is None:
        return {
            "version": 1,
            "kind": "failure_feedback_retry_brief",
            "required": False,
            "reason": "initial_cycle",
            "failure_closure_sha256": "",
            "failure_ownership": None,
            "validation_delta": None,
            "created_at": _now(),
        }
    if (
        decision.get("version") != 1
        or decision.get("kind") != "recovering_develop_replay_decision"
    ):
        raise ValueError("expected a version-1 recovering_develop_replay_decision")
    required = decision.get("action") == "retry"
    ownership = decision.get("failure_ownership")
    delta = decision.get("validation_delta")
    if required and (not isinstance(ownership, dict) or not isinstance(delta, dict)):
        raise ValueError("retry decision is missing failure ownership or validation delta")
    return {
        "version": 1,
        "kind": "failure_feedback_retry_brief",
        "required": required,
        "reason": "authorized_retry" if required else "no_retry_authorized",
        "failure_closure_sha256": stable_sha256(decision) if required else "",
        "failure_ownership": ownership if required else None,
        "validation_delta": delta if required else None,
        "created_at": _now(),
    }


def validate_preflight_delta(
    *,
    brief: dict[str, Any],
    preflight_evidence: dict[str, Any],
) -> dict[str, Any]:
    if brief.get("version") != 1 or brief.get("kind") != "failure_feedback_retry_brief":
        raise ValueError("expected a version-1 failure_feedback_retry_brief")
    if (
        preflight_evidence.get("version") != 1
        or preflight_evidence.get("kind") != "plan_preflight_evidence"
    ):
        raise ValueError("expected a version-1 plan_preflight_evidence receipt")
    if not brief.get("required"):
        return {
            "version": 1,
            "kind": "validation_delta_application",
            "required": False,
            "applied": True,
            "reason": "initial_or_handoff_cycle",
            "failure_closure_sha256": "",
            "matched_requirement_ids": [],
            "preflight_evidence_sha256": stable_sha256(preflight_evidence),
            "created_at": _now(),
        }

    delta = brief.get("validation_delta")
    if not isinstance(delta, dict):
        raise ValueError("retry brief validation_delta is required")
    check = _text(delta.get("discriminating_check"))
    if not check:
        raise ValueError("retry validation delta requires a discriminating check")
    plan = preflight_evidence.get("acceptance_plan")
    requirements = plan.get("requirements") if isinstance(plan, dict) else None
    if not isinstance(requirements, list):
        raise ValueError("preflight evidence is missing candidate-blind requirements")
    matched: list[str] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        strata = item.get("required_strata")
        if isinstance(strata, list) and check in strata:
            matched.append(_text(item.get("requirement_id")))
    if not matched:
        raise ValueError(
            "candidate-blind acceptance plan did not append the exact prior validation delta"
        )
    target_requirement_id = _text(delta.get("target_requirement_id"))
    if target_requirement_id and target_requirement_id not in matched:
        raise ValueError(
            "candidate-blind acceptance plan bound the retry discriminator to "
            "a requirement other than target_requirement_id"
        )
    return {
        "version": 1,
        "kind": "validation_delta_application",
        "required": True,
        "applied": True,
        "reason": "exact_discriminator_bound_to_candidate_blind_plan",
        "failure_closure_sha256": _text(brief.get("failure_closure_sha256")),
        "validation_delta_sha256": stable_sha256(delta),
        "matched_requirement_ids": matched,
        "preflight_evidence_sha256": stable_sha256(preflight_evidence),
        "created_at": _now(),
    }


def validate_preflight_repair(
    *,
    brief: dict[str, Any],
    transition_feedback: dict[str, Any],
    original: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any]:
    if brief.get("version") != 1 or brief.get("kind") != "failure_feedback_retry_brief":
        raise ValueError("expected a version-1 failure_feedback_retry_brief")
    if not brief.get("required"):
        raise ValueError(
            "canonical preflight repair requires an authorized retry brief"
        )
    delta = brief.get("validation_delta")
    if not isinstance(delta, dict):
        raise ValueError("retry brief validation_delta is required")
    check = _text(delta.get("discriminating_check"))
    if not check:
        raise ValueError("retry validation delta requires a discriminating check")
    ownership = brief.get("failure_ownership")
    if (
        not isinstance(ownership, dict)
        or _text(ownership.get("owner_role")) != "test_planner"
        or _text(ownership.get("failure_class")) != "acceptance_plan_gap"
    ):
        raise ValueError(
            "canonical preflight repair requires a planner-owned acceptance-plan gap"
        )
    for label, value in (("original", original), ("draft", draft)):
        if value.get("version") != 1 or value.get("kind") != "plan_preflight_evidence":
            raise ValueError(
                f"{label} must be a version-1 plan_preflight_evidence receipt"
            )
    if (
        transition_feedback.get("version") != 1
        or transition_feedback.get("kind") != "transition_failure_feedback"
    ):
        raise ValueError("expected a version-1 transition_failure_feedback receipt")
    if _text(transition_feedback.get("entry_id")) != _text(original.get("entry_id")):
        raise ValueError("transition feedback and canonical preflight entry must match")
    if _text(transition_feedback.get("current_state")) != _text(original.get("node")):
        raise ValueError("transition feedback and canonical preflight node must match")
    blocker_fingerprint = _text(transition_feedback.get("blocker_fingerprint"))
    if len(blocker_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in blocker_fingerprint.lower()
    ):
        raise ValueError("transition feedback requires a SHA-256 blocker fingerprint")
    failed_checks = transition_feedback.get("failed_checks")
    if not isinstance(failed_checks, list) or not any(
        isinstance(item, dict)
        and _text(item.get("repair_owner")) == "test_planner"
        and _text(item.get("failure_class")) == "acceptance_plan_gap"
        for item in failed_checks
    ):
        raise ValueError(
            "canonical preflight repair requires a test-planner acceptance-plan gap"
        )

    original_plan = original.get("acceptance_plan")
    draft_plan = draft.get("acceptance_plan")
    original_requirements = (
        original_plan.get("requirements") if isinstance(original_plan, dict) else None
    )
    draft_requirements = (
        draft_plan.get("requirements") if isinstance(draft_plan, dict) else None
    )
    if not isinstance(original_requirements, list) or not isinstance(
        draft_requirements, list
    ):
        raise ValueError("preflight evidence is missing candidate-blind requirements")
    if len(original_requirements) != len(draft_requirements):
        raise ValueError("repair draft must preserve requirement count and order")

    original_ids = [_requirement_id(item) for item in original_requirements]
    draft_ids = [_requirement_id(item) for item in draft_requirements]
    if len(set(original_ids)) != len(original_ids) or original_ids != draft_ids:
        raise ValueError(
            "repair draft must preserve unique requirement identities and order"
        )

    changed_requirement = ""
    normalized = copy.deepcopy(draft)
    normalized_requirements = normalized["acceptance_plan"]["requirements"]
    for index, (before, after) in enumerate(
        zip(original_requirements, draft_requirements)
    ):
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("candidate-blind requirements must be JSON objects")
        before_strata = before.get("required_strata")
        after_strata = after.get("required_strata")
        if not isinstance(before_strata, list) or not isinstance(after_strata, list):
            raise ValueError("candidate-blind required_strata must be arrays")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in before_strata + after_strata
        ):
            raise ValueError(
                "candidate-blind required_strata entries must be non-empty"
            )
        if len(set(before_strata)) != len(before_strata) or len(
            set(after_strata)
        ) != len(after_strata):
            raise ValueError("repair draft must not contain duplicate required_strata")
        if after_strata == before_strata:
            continue
        if changed_requirement:
            raise ValueError("repair draft may change exactly one requirement")
        if check in before_strata or after_strata != [*before_strata, check]:
            raise ValueError(
                "repair draft must append only the exact retry discriminating check"
            )
        changed_requirement = original_ids[index]
        normalized_requirements[index]["required_strata"] = copy.deepcopy(before_strata)

    if not changed_requirement:
        raise ValueError("repair draft did not append the retry discriminating check")
    if normalized != original:
        raise ValueError("repair draft changed evidence outside the authorized append")

    receipt = {
        "version": 1,
        "kind": "canonical_preflight_repair_transaction",
        "status": "validated",
        "required": True,
        "append_only": True,
        "requirement_id": changed_requirement,
        "failure_closure_sha256": _text(brief.get("failure_closure_sha256")),
        "validation_delta_sha256": stable_sha256(delta),
        "brief_sha256": stable_sha256(brief),
        "transition_feedback_sha256": stable_sha256(transition_feedback),
        "blocker_fingerprint": blocker_fingerprint,
        "original_preflight_sha256": stable_sha256(original),
        "draft_preflight_sha256": stable_sha256(draft),
        "canonical_preflight_sha256": stable_sha256(draft),
        "created_at": _now(),
    }
    receipt["receipt_sha256"] = stable_sha256(receipt)
    return receipt


def commit_preflight_repair(
    *,
    brief_path: Path,
    canonical_path: Path,
    draft_path: Path,
    raw_backup_path: Path,
    transition_feedback_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    paths = [
        brief_path,
        canonical_path,
        draft_path,
        raw_backup_path,
        transition_feedback_path,
        receipt_path,
    ]
    if len({_normalized_path(path) for path in paths}) != len(paths):
        raise ValueError("preflight repair transaction paths must be distinct")

    brief = _read_json(brief_path)
    transition_feedback = _read_json(transition_feedback_path)
    canonical = _read_json(canonical_path)
    draft = _read_json(draft_path)
    original = canonical
    already_committed = False
    if raw_backup_path.exists() and not raw_backup_path.is_file():
        raise ValueError("immutable raw preflight backup must be a regular file")
    if raw_backup_path.is_file():
        original = _read_json(raw_backup_path)
        original_sha = stable_sha256(original)
        canonical_sha = stable_sha256(canonical)
        draft_sha = stable_sha256(draft)
        if canonical_sha == draft_sha:
            already_committed = True
        elif canonical_sha != original_sha:
            raise ValueError("canonical preflight conflicts with immutable raw backup")

    receipt = validate_preflight_repair(
        brief=brief,
        transition_feedback=transition_feedback,
        original=original,
        draft=draft,
    )
    receipt["status"] = "already_committed" if already_committed else "committed"
    receipt["receipt_sha256"] = stable_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if already_committed:
        _write_json_atomic(receipt_path, receipt)
        return receipt

    wrote_raw = False
    try:
        if not raw_backup_path.exists():
            _write_json_atomic(raw_backup_path, original)
            wrote_raw = True
        _write_json_atomic(canonical_path, draft)
        committed = _read_json(canonical_path)
        if stable_sha256(committed) != receipt["canonical_preflight_sha256"]:
            raise OSError(
                "canonical preflight verification failed after atomic replace"
            )
        _write_json_atomic(receipt_path, receipt)
    except Exception:
        _write_json_atomic(canonical_path, original)
        receipt_path.unlink(missing_ok=True)
        if wrote_raw:
            raw_backup_path.unlink(missing_ok=True)
        raise
    return receipt


def build_targeted_preflight_repair(
    *,
    brief: dict[str, Any],
    original: dict[str, Any],
) -> dict[str, Any]:
    if brief.get("version") != 1 or brief.get("kind") != "failure_feedback_retry_brief":
        raise ValueError("expected a version-1 failure_feedback_retry_brief")
    if not brief.get("required"):
        raise ValueError("targeted preflight repair requires an authorized retry brief")
    delta = brief.get("validation_delta")
    if not isinstance(delta, dict):
        raise ValueError("retry brief validation_delta is required")
    check = _text(delta.get("discriminating_check"))
    target = _text(delta.get("target_requirement_id"))
    if not check:
        raise ValueError("retry validation delta requires a discriminating check")
    if not target:
        raise ValueError("targeted preflight repair requires target_requirement_id")
    if original.get("version") != 1 or original.get("kind") != "plan_preflight_evidence":
        raise ValueError("canonical preflight must be version-1 plan_preflight_evidence")
    plan = original.get("acceptance_plan")
    requirements = plan.get("requirements") if isinstance(plan, dict) else None
    if not isinstance(requirements, list):
        raise ValueError("preflight evidence is missing candidate-blind requirements")
    requirement_ids = [_requirement_id(item) for item in requirements]
    if len(set(requirement_ids)) != len(requirement_ids):
        raise ValueError("preflight evidence has duplicate requirement identities")
    if target not in requirement_ids:
        raise ValueError("target_requirement_id is not in the canonical preflight plan")
    index = requirement_ids.index(target)
    requirement = requirements[index]
    strata = requirement.get("required_strata") if isinstance(requirement, dict) else None
    if not isinstance(strata, list) or not all(
        isinstance(item, str) and item.strip() for item in strata
    ):
        raise ValueError("candidate-blind required_strata must be non-empty strings")
    if len(set(strata)) != len(strata):
        raise ValueError("canonical preflight contains duplicate required_strata")
    if check in strata:
        raise ValueError("target requirement already contains the retry discriminator")
    draft = copy.deepcopy(original)
    draft["acceptance_plan"]["requirements"][index]["required_strata"].append(check)
    return draft


def commit_targeted_preflight_repair(
    *,
    brief_path: Path,
    canonical_path: Path,
    raw_backup_path: Path,
    transition_feedback_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    paths = [
        brief_path,
        canonical_path,
        raw_backup_path,
        transition_feedback_path,
        receipt_path,
    ]
    if len({_normalized_path(path) for path in paths}) != len(paths):
        raise ValueError("targeted preflight repair transaction paths must be distinct")

    brief = _read_json(brief_path)
    transition_feedback = _read_json(transition_feedback_path)
    canonical = _read_json(canonical_path)
    original = canonical
    if raw_backup_path.exists() and not raw_backup_path.is_file():
        raise ValueError("immutable raw preflight backup must be a regular file")
    if raw_backup_path.is_file():
        original = _read_json(raw_backup_path)
    draft = build_targeted_preflight_repair(brief=brief, original=original)
    original_sha = stable_sha256(original)
    canonical_sha = stable_sha256(canonical)
    draft_sha = stable_sha256(draft)
    already_committed = canonical_sha == draft_sha
    if not already_committed and canonical_sha != original_sha:
        raise ValueError("canonical preflight conflicts with immutable raw backup")

    receipt = validate_preflight_repair(
        brief=brief,
        transition_feedback=transition_feedback,
        original=original,
        draft=draft,
    )
    target = _text(brief["validation_delta"].get("target_requirement_id"))
    if receipt["requirement_id"] != target:
        raise ValueError("targeted repair transaction changed the wrong requirement")
    receipt["status"] = "already_committed" if already_committed else "committed"
    receipt["receipt_sha256"] = stable_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if already_committed:
        _write_json_atomic(receipt_path, receipt)
        return receipt

    wrote_raw = False
    try:
        if not raw_backup_path.exists():
            _write_json_atomic(raw_backup_path, original)
            wrote_raw = True
        _write_json_atomic(canonical_path, draft)
        committed = _read_json(canonical_path)
        if stable_sha256(committed) != receipt["canonical_preflight_sha256"]:
            raise OSError(
                "canonical preflight verification failed after atomic replace"
            )
        _write_json_atomic(receipt_path, receipt)
    except Exception:
        _write_json_atomic(canonical_path, original)
        receipt_path.unlink(missing_ok=True)
        if wrote_raw:
            raw_backup_path.unlink(missing_ok=True)
        raise
    return receipt


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _requirement_id(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("candidate-blind requirements must be JSON objects")
    identifier = _text(value.get("requirement_id"))
    if not identifier:
        raise ValueError("candidate-blind requirement_id is required")
    return identifier


def _normalized_path(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
