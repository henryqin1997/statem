from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    from statem.miniyaml import loads as _yaml_loads
else:
    _yaml_loads = yaml.safe_load

try:
    from .artifact_identity import (
        artifact_identity,
        file_sha256,
        public_contract_snapshot,
        stable_sha256,
    )
except ImportError:
    from artifact_identity import (  # type: ignore[no-redef]
        artifact_identity,
        file_sha256,
        public_contract_snapshot,
        stable_sha256,
    )


DEFAULT_DIR = Path("/tmp/statem-verification-checks/multirole")
DEFAULT_SEAL = DEFAULT_DIR / "contract-seal.json"
DEFAULT_PROPOSAL = DEFAULT_DIR / "candidate-proposal.json"
DEFAULT_CONTEXT_VIEW = DEFAULT_DIR / "falsifier-context-view.json"
DEFAULT_DECISION = DEFAULT_DIR / "promotion-decision.json"
DEFAULT_APPLICATION = DEFAULT_DIR / "application-receipt.json"
DEFAULT_BASELINE_SNAPSHOT = Path(
    "/tmp/statem-verification-checks/artifact-provider/baseline-snapshot.json"
)
DEFAULT_CANDIDATE_SNAPSHOT = Path(
    "/tmp/statem-verification-checks/artifact-provider/candidate-snapshot.json"
)
DEFAULT_PROVIDER_APPLICATION = Path(
    "/tmp/statem-verification-checks/artifact-provider/application.json"
)
DEFAULT_REVIEW_PRACTICES = Path(
    "/tmp/statem-verification-checks/reviewer-practices-v1.yaml"
)
DEFAULT_REVIEW_PROFILE = DEFAULT_DIR / "review-profile.json"
DEFAULT_SOLVER_PLAN = DEFAULT_DIR / "solver-plan.json"
DEFAULT_PREFLIGHT_CONTEXT_VIEW = DEFAULT_DIR / "preflight-context-view.json"
DEFAULT_PREFLIGHT_TASK = DEFAULT_DIR / "preflight-task.json"
DEFAULT_PREFLIGHT_EVIDENCE = DEFAULT_DIR / "preflight-evidence.json"
DEFAULT_REVIEW_PROFILE_CATALOG = Path(
    "/tmp/statem-verification-checks/reviewer-practice-router-v1.yaml"
)
PROPOSAL_FIELDS = {
    "target_gap",
    "hypothesis",
    "counter_hypothesis",
    "protected_behavior",
    "protected_behavior_basis",
    "discriminating_checks",
    "rollback_artifact_identity",
    "rollback_locator",
}
LEGACY_PROPOSAL_FIELDS = PROPOSAL_FIELDS - {"protected_behavior_basis"}
VERDICTS = {"accept", "reject", "inconclusive"}
CONTRACT_POLICIES = {"strict_docs", "repair_aware"}
PROVENANCE_BASES = {
    "task_source",
    "public_signature",
    "public_consumer",
    "normative_definition",
    "cross_module_invariant",
}
REGRESSION_SEVERITIES = {"blocking", "advisory"}
PROTECTION_STATUSES = {"corroborated", "falsified", "unresolved"}
PROFILE_RECEIPT_STATUSES = {"applied", "not_applicable", "unresolved"}
SOLVER_PLAN_FIELDS = {
    "objective",
    "steps",
    "assumptions",
    "planned_checks",
    "mutation_scope",
    "success_criteria",
}
CONTEXT_BUNDLE_MAX_BYTES = 160_000
CONTEXT_BUNDLE_FILE_MAX_BYTES = 40_000
CONTEXT_BUNDLE_EXCLUDED_PARTS = {
    ".git",
    ".statem",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
CONTEXT_BUNDLE_EXCLUDED_NAMES = {"progress.md"}
CONTEXT_BUNDLE_DEPRIORITIZED_PARTS = {
    ".venv",
    "_vendor",
    "dist-packages",
    "site-packages",
    "third-party",
    "third_party",
    "vendor",
    "vendored",
    "venv",
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "seal":
            receipt = seal_contract(
                artifact_root=args.artifact_root,
                contract_sources=args.contract_source,
                contract_policy=args.contract_policy,
                baseline_snapshot=(
                    _read_json(args.baseline_snapshot)
                    if args.baseline_snapshot is not None
                    else None
                ),
            )
            _write_json(args.output, receipt)
        elif args.action == "proposal":
            previous_proposal = (
                _read_json(args.output) if args.output.is_file() else None
            )
            receipt = record_proposal(
                draft=_read_json(args.draft),
                seal=_read_json(args.seal),
                artifact_root=args.artifact_root,
                previous_proposal=previous_proposal,
                preflight_evidence=(
                    _read_json(args.preflight_evidence)
                    if args.preflight_evidence is not None
                    else None
                ),
            )
            _write_json(args.output, receipt)
        elif args.action == "plan":
            receipt = record_solver_plan(
                draft=_read_json(args.draft),
                seal=_read_json(args.seal),
                review_profile=_read_json(args.review_profile),
            )
            _write_json(args.output, receipt)
        elif args.action == "preflight-task":
            receipt = preflight_task(
                plan=_read_json(args.plan),
                seal=_read_json(args.seal),
                context_view=_read_json(args.context_view),
                review_profile=_read_json(args.review_profile),
            )
            _write_json(args.output, receipt)
        elif args.action == "preflight-evidence":
            reviewer_result = (
                _read_json(args.reviewer_result)
                if args.reviewer_result is not None
                else _load_current_role_result("preflight-reviewer")
            )
            receipt = record_preflight_evidence(
                plan=_read_json(args.plan),
                seal=_read_json(args.seal),
                context_view=_read_json(args.context_view),
                review_profile=_read_json(args.review_profile),
                reviewer_result=reviewer_result,
            )
            _write_json(args.output, receipt)
        elif args.action == "require-preflight":
            receipt = require_preflight_binding(
                proposal=_read_json(args.proposal),
                preflight_evidence=_read_json(args.preflight_evidence),
                reviewer_result=_load_current_role_result("preflight-reviewer"),
            )
        elif args.action == "decide":
            falsifier = (
                _read_json(args.falsifier_result)
                if args.falsifier_result is not None
                else _load_current_falsifier_result()
            )
            receipt = decide_promotion(
                seal=_read_json(args.seal),
                proposal=_read_json(args.proposal),
                context_view=_read_json(args.context_view),
                falsifier=falsifier,
                artifact_root=args.artifact_root,
                baseline_snapshot=(
                    _read_json(args.baseline_snapshot)
                    if args.baseline_snapshot is not None
                    else None
                ),
                candidate_snapshot=(
                    _read_json(args.candidate_snapshot)
                    if args.candidate_snapshot is not None
                    else None
                ),
                review_practices=(
                    _read_yaml(args.review_practices)
                    if args.review_practices is not None
                    else None
                ),
                review_profile=(
                    _read_json(args.review_profile)
                    if args.review_profile is not None
                    else None
                ),
            )
            receipt = _reuse_equivalent_receipt(
                args.output,
                receipt,
                volatile_fields={"created_at"},
            )
            _write_json(args.output, receipt)
        elif args.action == "context-view":
            receipt = record_context_view(
                role=args.role,
                included_paths=args.include,
                snapshot_receipts=[_read_json(path) for path in args.include_snapshot],
            )
            _write_json(args.output, receipt)
        elif args.action == "review-profile":
            receipt = record_review_profile(
                draft=_read_json(args.draft),
                catalog=_read_yaml(args.catalog),
                catalog_root=args.catalog.parent,
                seal=_read_json(args.seal),
            )
            _write_json(args.output, receipt)
        elif args.action == "falsifier-task":
            receipt = falsifier_task(
                proposal=_read_json(args.proposal),
                seal=_read_json(args.seal),
                context_view=_read_json(args.context_view),
                review_practices=(
                    _read_yaml(args.review_practices)
                    if args.review_practices is not None
                    else None
                ),
                review_profile=(
                    _read_json(args.review_profile)
                    if args.review_profile is not None
                    else None
                ),
            )
            _write_json(args.output, receipt)
        elif args.action == "require":
            decision = _read_json(args.decision)
            require_decision(decision, set(args.allow))
            receipt = decision
        elif args.action == "verify-application":
            receipt = verify_application(
                decision=_read_json(args.decision),
                seal=_read_json(args.seal),
                artifact_root=args.artifact_root,
                mode=args.mode,
                review_route=(
                    _read_json(args.review_route)
                    if args.review_route is not None
                    else None
                ),
                provider_application=(
                    _read_json(args.provider_application)
                    if args.provider_application is not None
                    else None
                ),
            )
            _write_json(args.output, receipt)
        else:
            parser.error(f"unknown action: {args.action}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"multirole promotion gate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic authorization gate for a role-separated challenger flow."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    seal = subparsers.add_parser("seal")
    seal.add_argument("--artifact-root", type=Path, default=Path("/app"))
    seal.add_argument("--contract-source", type=Path, action="append", default=[])
    seal.add_argument(
        "--contract-policy",
        choices=sorted(CONTRACT_POLICIES),
        default="strict_docs",
    )
    seal.add_argument("--output", type=Path, default=DEFAULT_SEAL)
    seal.add_argument("--baseline-snapshot", type=Path)

    proposal = subparsers.add_parser("proposal")
    proposal.add_argument("--draft", type=Path, required=True)
    proposal.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    proposal.add_argument("--artifact-root", type=Path, default=Path("/app"))
    proposal.add_argument("--preflight-evidence", type=Path)
    proposal.add_argument("--output", type=Path, default=DEFAULT_PROPOSAL)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--draft", type=Path, required=True)
    plan.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    plan.add_argument("--review-profile", type=Path, default=DEFAULT_REVIEW_PROFILE)
    plan.add_argument("--output", type=Path, default=DEFAULT_SOLVER_PLAN)

    preflight_task_parser = subparsers.add_parser("preflight-task")
    preflight_task_parser.add_argument("--plan", type=Path, default=DEFAULT_SOLVER_PLAN)
    preflight_task_parser.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    preflight_task_parser.add_argument(
        "--context-view", type=Path, default=DEFAULT_PREFLIGHT_CONTEXT_VIEW
    )
    preflight_task_parser.add_argument(
        "--review-profile", type=Path, default=DEFAULT_REVIEW_PROFILE
    )
    preflight_task_parser.add_argument("--output", type=Path, default=DEFAULT_PREFLIGHT_TASK)

    preflight_evidence = subparsers.add_parser("preflight-evidence")
    preflight_evidence.add_argument("--plan", type=Path, default=DEFAULT_SOLVER_PLAN)
    preflight_evidence.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    preflight_evidence.add_argument(
        "--context-view", type=Path, default=DEFAULT_PREFLIGHT_CONTEXT_VIEW
    )
    preflight_evidence.add_argument(
        "--review-profile", type=Path, default=DEFAULT_REVIEW_PROFILE
    )
    preflight_evidence.add_argument("--reviewer-result", type=Path)
    preflight_evidence.add_argument("--output", type=Path, default=DEFAULT_PREFLIGHT_EVIDENCE)

    require_preflight = subparsers.add_parser("require-preflight")
    require_preflight.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    require_preflight.add_argument(
        "--preflight-evidence", type=Path, default=DEFAULT_PREFLIGHT_EVIDENCE
    )

    decide = subparsers.add_parser("decide")
    decide.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    decide.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    decide.add_argument("--context-view", type=Path, default=DEFAULT_CONTEXT_VIEW)
    decide.add_argument("--falsifier-result", type=Path)
    decide.add_argument("--artifact-root", type=Path, default=Path("/app"))
    decide.add_argument("--baseline-snapshot", type=Path)
    decide.add_argument("--candidate-snapshot", type=Path)
    decide.add_argument("--review-practices", type=Path)
    decide.add_argument("--review-profile", type=Path)
    decide.add_argument("--output", type=Path, default=DEFAULT_DECISION)

    context_view = subparsers.add_parser("context-view")
    context_view.add_argument(
        "--role",
        choices=("contract_auditor", "preflight_reviewer", "falsifier"),
        required=True,
    )
    context_view.add_argument("--include", type=Path, action="append", required=True)
    context_view.add_argument("--include-snapshot", type=Path, action="append", default=[])
    context_view.add_argument("--output", type=Path, default=DEFAULT_CONTEXT_VIEW)

    review_profile = subparsers.add_parser("review-profile")
    review_profile.add_argument("--draft", type=Path, required=True)
    review_profile.add_argument("--catalog", type=Path, default=DEFAULT_REVIEW_PROFILE_CATALOG)
    review_profile.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    review_profile.add_argument("--output", type=Path, default=DEFAULT_REVIEW_PROFILE)

    task = subparsers.add_parser("falsifier-task")
    task.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    task.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    task.add_argument("--context-view", type=Path, default=DEFAULT_CONTEXT_VIEW)
    task.add_argument("--review-practices", type=Path)
    task.add_argument("--review-profile", type=Path)
    task.add_argument("--output", type=Path, required=True)

    require = subparsers.add_parser("require")
    require.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    require.add_argument(
        "--allow",
        action="append",
        choices=("promote", "revise", "rollback", "inconclusive"),
        required=True,
    )

    verify = subparsers.add_parser("verify-application")
    verify.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    verify.add_argument("--seal", type=Path, default=DEFAULT_SEAL)
    verify.add_argument("--artifact-root", type=Path, default=Path("/app"))
    verify.add_argument(
        "--mode", choices=("promote", "quarantine", "rollback"), required=True
    )
    verify.add_argument("--review-route", type=Path)
    verify.add_argument(
        "--provider-application",
        type=Path,
    )
    verify.add_argument("--output", type=Path, default=DEFAULT_APPLICATION)
    return parser


def seal_contract(
    *,
    artifact_root: Path,
    contract_sources: list[Path],
    contract_policy: str = "strict_docs",
    baseline_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if contract_policy not in CONTRACT_POLICIES:
        raise ValueError(f"unsupported contract policy: {contract_policy}")
    context = _state_context()
    sources: list[dict[str, str]] = []
    for path in contract_sources:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"contract source is not a file: {resolved}")
        sources.append({"path": str(resolved), "sha256": file_sha256(resolved)})
    snapshot = public_contract_snapshot(artifact_root)
    baseline_identity = artifact_identity(artifact_root)
    if baseline_snapshot is not None:
        _require_receipt(baseline_snapshot, "filesystem_artifact_snapshot")
        if baseline_snapshot.get("snapshot_kind") != "baseline":
            raise ValueError("contract seal requires a baseline snapshot")
        if baseline_snapshot.get("artifact_identity") != baseline_identity:
            raise ValueError("baseline snapshot does not match the live contract artifact")
    return {
        "version": 1,
        "kind": "contract_seal",
        **context,
        "producer": {
            "agent_id": f"stateful-hook:{context['run_id']}:{context['entry_id']}",
            "role": "stateful_hook",
        },
        "invoked_by": _producer(),
        "baseline_artifact_identity": baseline_identity,
        "baseline_snapshot_sha256": (
            stable_sha256(baseline_snapshot) if baseline_snapshot is not None else None
        ),
        "baseline_snapshot_path": (
            baseline_snapshot.get("snapshot_path") if baseline_snapshot is not None else None
        ),
        "contract_sources": sources,
        "public_contract_snapshot": snapshot,
        "public_contract_snapshot_sha256": stable_sha256(snapshot),
        "contract_policy": contract_policy,
        "artifact_transaction": "filesystem_snapshot_provider",
        "created_at": _now(),
    }


def record_proposal(
    *,
    draft: dict[str, Any],
    seal: dict[str, Any],
    artifact_root: Path,
    previous_proposal: dict[str, Any] | None = None,
    preflight_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(seal, "contract_seal")
    producer = _producer()
    if producer["role"] != "solver":
        raise ValueError("candidate proposal requires StateM agent role 'solver'")
    required_fields = (
        PROPOSAL_FIELDS if seal.get("baseline_snapshot_sha256") else LEGACY_PROPOSAL_FIELDS
    )
    missing = sorted(required_fields - set(draft))
    unknown = sorted(set(draft) - PROPOSAL_FIELDS)
    if missing:
        raise ValueError("proposal draft is missing: " + ", ".join(missing))
    if unknown:
        raise ValueError("proposal draft has unknown fields: " + ", ".join(unknown))
    for key in (
        "target_gap",
        "hypothesis",
        "counter_hypothesis",
        "rollback_artifact_identity",
        "rollback_locator",
    ):
        if not _text(draft.get(key)):
            raise ValueError(f"proposal draft {key} must be non-empty")
    for key in ("protected_behavior", "discriminating_checks"):
        if not _string_list(draft.get(key)):
            raise ValueError(f"proposal draft {key} must be a non-empty string list")
    if "protected_behavior_basis" in draft:
        protected_basis = _protected_behavior_basis(draft.get("protected_behavior_basis"))
        protected_behaviors = set(draft["protected_behavior"])
        if {item["behavior"] for item in protected_basis} != protected_behaviors:
            raise ValueError(
                "protected_behavior_basis must bind every protected behavior exactly once"
            )
    if draft["rollback_artifact_identity"] != seal["baseline_artifact_identity"]:
        raise ValueError("proposal rollback identity must match the sealed baseline")
    if seal.get("baseline_snapshot_path") and (
        draft["rollback_locator"] != seal["baseline_snapshot_path"]
    ):
        raise ValueError("proposal rollback locator must match the sealed provider snapshot")
    context = _state_context()
    if context["run_id"] != seal["run_id"]:
        raise ValueError("proposal and contract seal run ids differ")
    supersedes: str | None = None
    protected_behavior_delta: dict[str, list[str]] | None = None
    preflight_evidence_sha256: str | None = None
    if preflight_evidence is not None:
        _require_receipt(preflight_evidence, "plan_preflight_evidence")
        preflight_producer = preflight_evidence.get("producer")
        if not isinstance(preflight_producer, dict) or preflight_producer.get(
            "role"
        ) != "preflight-reviewer":
            raise ValueError("preflight evidence requires the preflight-reviewer role")
        if preflight_evidence.get("run_id") != context["run_id"]:
            raise ValueError("proposal and preflight evidence run ids differ")
        if preflight_evidence.get("entry_id") != context["entry_id"]:
            raise ValueError("proposal and preflight evidence entry ids differ")
        if preflight_evidence.get("contract_seal_sha256") != stable_sha256(seal):
            raise ValueError("preflight evidence is not bound to the contract seal")
        preflight_evidence_sha256 = stable_sha256(preflight_evidence)
    if context["node"] == "revise":
        if previous_proposal is None:
            raise ValueError("revision requires the previous candidate proposal")
        _require_receipt(previous_proposal, "candidate_proposal")
        if previous_proposal.get("run_id") != context["run_id"]:
            raise ValueError("revision proposal belongs to another StateM run")
        previous = set(previous_proposal.get("protected_behavior") or [])
        current = set(draft["protected_behavior"])
        protected_behavior_delta = {
            "added": sorted(current - previous),
            "withdrawn": sorted(previous - current),
            "retained": sorted(previous & current),
        }
        supersedes = stable_sha256(previous_proposal)
        if preflight_evidence_sha256 is None:
            preflight_evidence_sha256 = _text(
                previous_proposal.get("preflight_evidence_sha256")
            ) or None
    return {
        "version": 1,
        "kind": "candidate_proposal",
        **context,
        "producer": producer,
        "contract_seal_sha256": stable_sha256(seal),
        "baseline_artifact_identity": seal["baseline_artifact_identity"],
        "candidate_artifact_identity": artifact_identity(artifact_root),
        "supersedes_proposal_sha256": supersedes,
        "preflight_evidence_sha256": preflight_evidence_sha256,
        "protected_behavior_delta": protected_behavior_delta,
        **draft,
        "created_at": _now(),
    }


def record_solver_plan(
    *,
    draft: dict[str, Any],
    seal: dict[str, Any],
    review_profile: dict[str, Any],
) -> dict[str, Any]:
    _require_receipt(seal, "contract_seal")
    _require_receipt(review_profile, "review_profile_selection")
    context = _state_context()
    producer = _producer()
    if context["node"] != "solve" or producer.get("role") != "solver":
        raise ValueError("solver plan belongs to the solve entry and solver role")
    if set(draft) != SOLVER_PLAN_FIELDS:
        missing = sorted(SOLVER_PLAN_FIELDS - set(draft))
        unknown = sorted(set(draft) - SOLVER_PLAN_FIELDS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise ValueError("solver plan requires the exact schema: " + "; ".join(detail))
    if not _text(draft.get("objective")):
        raise ValueError("solver plan objective must be non-empty")
    for field in ("steps", "planned_checks", "mutation_scope", "success_criteria"):
        if not _string_list(draft.get(field)):
            raise ValueError(f"solver plan {field} must be a non-empty string list")
    assumptions = draft.get("assumptions")
    if not isinstance(assumptions, list) or not all(_text(item) for item in assumptions):
        raise ValueError("solver plan assumptions must be a string list")
    if context["run_id"] != seal.get("run_id"):
        raise ValueError("solver plan and contract seal run ids differ")
    if review_profile.get("run_id") != context["run_id"]:
        raise ValueError("solver plan and review profile run ids differ")
    if review_profile.get("contract_seal_sha256") != stable_sha256(seal):
        raise ValueError("review profile is not bound to the contract seal")
    return {
        "version": 1,
        "kind": "solver_plan",
        **context,
        "producer": producer,
        "contract_seal_sha256": stable_sha256(seal),
        "review_profile_sha256": stable_sha256(review_profile),
        **draft,
        "created_at": _now(),
    }


def preflight_task(
    *,
    plan: dict[str, Any],
    seal: dict[str, Any],
    context_view: dict[str, Any],
    review_profile: dict[str, Any],
) -> dict[str, Any]:
    _require_receipt(plan, "solver_plan")
    _require_receipt(seal, "contract_seal")
    _require_receipt(context_view, "context_view")
    _require_receipt(review_profile, "review_profile_selection")
    plan_sha256 = stable_sha256(plan)
    seal_sha256 = stable_sha256(seal)
    profile_sha256 = stable_sha256(review_profile)
    if plan.get("contract_seal_sha256") != seal_sha256:
        raise ValueError("solver plan is not bound to the contract seal")
    if plan.get("review_profile_sha256") != profile_sha256:
        raise ValueError("solver plan is not bound to the review profile")
    if review_profile.get("contract_seal_sha256") != seal_sha256:
        raise ValueError("review profile is not bound to the contract seal")
    if context_view.get("consumer_role") != "preflight_reviewer":
        raise ValueError("preflight context view has the wrong consumer role")
    for receipt in (seal, context_view, review_profile):
        if receipt.get("run_id") != plan.get("run_id"):
            raise ValueError("preflight inputs belong to different StateM runs")
    if context_view.get("entry_id") != plan.get("entry_id"):
        raise ValueError("preflight context view belongs to another solve entry")
    if not _context_view_matches(context_view):
        raise ValueError("preflight context view changed after it was recorded")
    context_view_sha256 = stable_sha256(context_view)
    return {
        "tasks": [
            {
                "task_id": "preflight_plan_review",
                "priority": 1,
                "plan_sha256": plan_sha256,
                "contract_seal_sha256": seal_sha256,
                "context_view_sha256": context_view_sha256,
                "review_profile_sha256": profile_sha256,
                "context_bundle": _context_bundle(context_view),
                "review_profile": review_profile,
                "assignment": (
                    "Review the solver plan before a candidate exists, using only the "
                    "embedded context_bundle and selected review_profile. This is a "
                    "tool-free, read-only advisory review. Inspect the hard-versus-defeasible "
                    "contract boundary, assumptions, mutation scope, planned checks, success "
                    "criteria, category-specific checklist gaps, and likely failure modes. "
                    "Do not inspect external files, execute commands, repair artifacts, invent "
                    "candidate evidence, or authorize promotion. Return generic TeamRun fields "
                    "status, summary, claims, evidence, coverage, children, and prune_proposals, "
                    "plus exact top-level fields advisory_verdict, plan_sha256, "
                    "contract_seal_sha256, context_view_sha256, review_profile_sha256, "
                    "plan_findings, checklist_gaps, assumption_risks, and recommendations. "
                    "advisory_verdict is ready or revise_plan. The four finding fields are "
                    "lists of concise strings. Bind every supplied hash exactly. Use status "
                    "completed and coverage.complete=true only after reviewing the full bundle."
                ),
            }
        ]
    }


def record_preflight_evidence(
    *,
    plan: dict[str, Any],
    seal: dict[str, Any],
    context_view: dict[str, Any],
    review_profile: dict[str, Any],
    reviewer_result: dict[str, Any],
) -> dict[str, Any]:
    _require_receipt(plan, "solver_plan")
    _require_receipt(seal, "contract_seal")
    _require_receipt(context_view, "context_view")
    _require_receipt(review_profile, "review_profile_selection")
    preflight_task(
        plan=plan,
        seal=seal,
        context_view=context_view,
        review_profile=review_profile,
    )
    context = _state_context()
    if context["node"] != "solve":
        raise ValueError("preflight evidence must be recorded in the solve entry")
    for field in ("run_id", "node", "entry_id"):
        if reviewer_result.get(field) != context[field]:
            raise ValueError(f"preflight reviewer result {field} differs from current entry")
    producer = reviewer_result.get("producer")
    if not isinstance(producer, dict) or producer.get("role") != "preflight-reviewer":
        raise ValueError("preflight evidence requires exactly one preflight-reviewer result")
    if reviewer_result.get("status") not in {"completed", "terminal"}:
        raise ValueError("preflight reviewer did not complete")
    coverage = reviewer_result.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        raise ValueError("preflight reviewer coverage is incomplete")
    raw = reviewer_result.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("preflight reviewer result is missing its raw payload")
    raw_coverage = raw.get("coverage")
    if raw.get("status") not in {"completed", "terminal"} or not isinstance(
        raw_coverage, dict
    ) or raw_coverage.get("complete") is not True:
        raise ValueError("preflight reviewer raw payload is incomplete")
    expected_hashes = {
        "plan_sha256": stable_sha256(plan),
        "contract_seal_sha256": stable_sha256(seal),
        "context_view_sha256": stable_sha256(context_view),
        "review_profile_sha256": stable_sha256(review_profile),
    }
    for field, expected in expected_hashes.items():
        if raw.get(field) != expected:
            raise ValueError(f"preflight reviewer {field} binding is invalid")
    verdict = _text(raw.get("advisory_verdict"))
    if verdict not in {"ready", "revise_plan"}:
        raise ValueError("preflight advisory verdict must be ready or revise_plan")
    finding_fields = (
        "plan_findings",
        "checklist_gaps",
        "assumption_risks",
        "recommendations",
    )
    for field in finding_fields:
        value = raw.get(field)
        if not isinstance(value, list) or not all(_text(item) for item in value):
            raise ValueError(f"preflight reviewer {field} must be a string list")
    if plan.get("run_id") != context["run_id"] or plan.get("entry_id") != context[
        "entry_id"
    ]:
        raise ValueError("solver plan belongs to another solve entry")
    return {
        "version": 1,
        "kind": "plan_preflight_evidence",
        **context,
        "producer": producer,
        **expected_hashes,
        "advisory_verdict": verdict,
        **{field: list(raw[field]) for field in finding_fields},
        "promotion_authority": False,
        "created_at": reviewer_result.get("submitted_at") or _now(),
    }


def require_preflight_binding(
    *,
    proposal: dict[str, Any],
    preflight_evidence: dict[str, Any],
    reviewer_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(proposal, "candidate_proposal")
    _require_receipt(preflight_evidence, "plan_preflight_evidence")
    if proposal.get("preflight_evidence_sha256") != stable_sha256(preflight_evidence):
        raise ValueError("candidate proposal is not bound to the preflight evidence")
    if proposal.get("run_id") != preflight_evidence.get("run_id"):
        raise ValueError("candidate proposal and preflight evidence run ids differ")
    if proposal.get("entry_id") != preflight_evidence.get("entry_id"):
        raise ValueError("candidate proposal and preflight evidence entry ids differ")
    if proposal.get("contract_seal_sha256") != preflight_evidence.get(
        "contract_seal_sha256"
    ):
        raise ValueError("candidate proposal and preflight evidence seals differ")
    if preflight_evidence.get("promotion_authority") is not False:
        raise ValueError("preflight evidence cannot carry promotion authority")
    if reviewer_result is not None:
        _require_preflight_result_binding(preflight_evidence, reviewer_result)
    return preflight_evidence


def _require_preflight_result_binding(
    evidence: dict[str, Any], reviewer_result: dict[str, Any]
) -> None:
    for field in ("run_id", "node", "entry_id"):
        if reviewer_result.get(field) != evidence.get(field):
            raise ValueError(f"preflight evidence {field} differs from TeamRun result")
    if reviewer_result.get("producer") != evidence.get("producer"):
        raise ValueError("preflight evidence producer differs from TeamRun result")
    if reviewer_result.get("status") not in {"completed", "terminal"}:
        raise ValueError("bound preflight TeamRun result did not complete")
    coverage = reviewer_result.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        raise ValueError("bound preflight TeamRun result has incomplete coverage")
    raw = reviewer_result.get("raw")
    if not isinstance(raw, dict):
        raise ValueError("bound preflight TeamRun result has no raw payload")
    fields = (
        "advisory_verdict",
        "plan_sha256",
        "contract_seal_sha256",
        "context_view_sha256",
        "review_profile_sha256",
        "plan_findings",
        "checklist_gaps",
        "assumption_risks",
        "recommendations",
    )
    if any(raw.get(field) != evidence.get(field) for field in fields):
        raise ValueError("preflight evidence differs from the immutable TeamRun payload")
    submitted_at = reviewer_result.get("submitted_at")
    if submitted_at and evidence.get("created_at") != submitted_at:
        raise ValueError("preflight evidence timestamp differs from TeamRun submission")


def record_context_view(
    *,
    role: str,
    included_paths: list[Path],
    snapshot_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = _state_context()
    included_paths = list(included_paths)
    for receipt in snapshot_receipts or []:
        _require_receipt(receipt, "filesystem_artifact_snapshot")
        included_paths.append(Path(_text(receipt.get("snapshot_path"))))
    included: list[dict[str, str]] = []
    for path in included_paths:
        resolved = path.expanduser().resolve()
        if resolved.is_file():
            identity = "file-sha256:" + file_sha256(resolved)
            kind = "file"
        elif resolved.is_dir():
            identity = artifact_identity(resolved)
            kind = "directory"
        else:
            raise ValueError(f"context-view include path does not exist: {resolved}")
        included.append({"path": str(resolved), "kind": kind, "identity": identity})
    return {
        "version": 1,
        "kind": "context_view",
        **context,
        "producer": {
            "agent_id": f"context-hook:{context['run_id']}:{context['entry_id']}",
            "role": "stateful_hook",
        },
        "consumer_role": role,
        "included": included,
        "excluded_information_classes": [
            "credentials",
            "provider_config",
            "raw_model_sessions",
            "solver_trajectory",
            "hidden_benchmark_artifacts",
            "verifier_internals",
            "sibling_worker_state",
        ],
        "excluded_paths": ["/app/progress.md"],
        "enforcement": "state_identity_plus_scoped_read_only_worker",
        "created_at": _now(),
    }


def record_review_profile(
    *,
    draft: dict[str, Any],
    catalog: dict[str, Any],
    catalog_root: Path,
    seal: dict[str, Any],
) -> dict[str, Any]:
    _require_receipt(seal, "contract_seal")
    context = _state_context()
    producer = _producer()
    if context["node"] != "contract_audit" or producer.get("role") != "solver":
        raise ValueError("review profile selection belongs to contract_audit")
    if set(draft) != {"primary", "secondary", "evidence"}:
        raise ValueError("review profile draft requires exactly primary, secondary, and evidence")
    primary = _text(draft.get("primary"))
    secondary = draft.get("secondary")
    evidence = draft.get("evidence")
    if not isinstance(secondary, list) or not all(_text(item) for item in secondary):
        raise ValueError("review profile secondary must be a string list")
    if not _string_list(evidence):
        raise ValueError("review profile evidence must be a non-empty string list")
    if primary in secondary or len(set(secondary)) != len(secondary):
        raise ValueError("review profiles must be unique")

    base_file, profiles, max_secondary = _review_profile_catalog(catalog)
    if primary not in profiles or any(item not in profiles for item in secondary):
        raise ValueError("review profile selection contains an unknown profile")
    if len(secondary) > max_secondary:
        raise ValueError("review profile selection exceeds the secondary profile budget")

    selected_files = [("base", base_file)] + [
        (profile_id, profiles[profile_id]["file"])
        for profile_id in [primary, *secondary]
    ]
    documents: list[dict[str, Any]] = []
    for profile_id, filename in selected_files:
        path = (catalog_root / filename).resolve()
        if not path.is_file():
            path = (catalog_root / "reviewer" / filename).resolve()
        if not path.is_file():
            raise ValueError(f"review profile file is missing: {filename}")
        documents.append(
            {
                "profile_id": profile_id,
                "path": str(path),
                "sha256": file_sha256(path),
                "content": path.read_text(encoding="utf-8"),
                "checks": (
                    list(profiles[profile_id]["checks"])
                    if profile_id in profiles
                    else []
                ),
            }
        )
    return {
        "version": 1,
        "kind": "review_profile_selection",
        **context,
        "producer": producer,
        "contract_seal_sha256": stable_sha256(seal),
        "catalog_sha256": stable_sha256(catalog),
        "primary": primary,
        "secondary": secondary,
        "evidence": evidence,
        "documents": documents,
        "created_at": _now(),
    }


def falsifier_task(
    *,
    proposal: dict[str, Any],
    seal: dict[str, Any],
    context_view: dict[str, Any],
    review_practices: dict[str, Any] | None = None,
    review_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(proposal, "candidate_proposal")
    _require_receipt(seal, "contract_seal")
    _require_receipt(context_view, "context_view")
    context_bundle = _context_bundle(context_view)
    review_protocol = (
        _review_protocol(review_practices)
        if review_practices is not None
        else None
    )
    if review_profile is not None:
        _require_receipt(review_profile, "review_profile_selection")
        if review_profile.get("contract_seal_sha256") != stable_sha256(seal):
            raise ValueError("review profile is not bound to the contract seal")
    return {
        "tasks": [
            {
                "task_id": "independent_falsification",
                "priority": 1,
                "candidate_artifact_identity": proposal["candidate_artifact_identity"],
                "contract_seal_sha256": stable_sha256(seal),
                "context_view_sha256": stable_sha256(context_view),
                "context_bundle": context_bundle,
                "review_protocol": review_protocol,
                "review_profile": review_profile,
                "assignment": (
                    "Independently try to falsify the candidate using only context_bundle, "
                    "which is a trusted read-only projection of the allowed context view. "
                    "Do not call tools, commands, or filesystem APIs; every allowed source "
                    "is embedded in this assignment. "
                    "Exercise the stated counter-hypothesis, protected behavior, and "
                    "discriminating checks. Audit every protected behavior's provenance: "
                    "under repair_aware policy, a behavioral docstring in a broken target "
                    "module is not a hard contract unless task wording, a public signature, "
                    "a public consumer replay, or a normative definition corroborates it. "
                    "Do not expand the task contract with unrelated edge cases. Call an "
                    "issue a regression only when paired baseline/candidate evidence shows "
                    "the candidate introduced it; when the contract names an exact public "
                    "oracle, version, or normative consumer, compare both artifacts to that "
                    "reference on the same case because the baseline is defeasible evidence, "
                    "not an authority. Otherwise record it as residual "
                    "counterevidence. For named algorithms with multiple standard variants, "
                    "challenge a protected variant whose only basis is a broken module's "
                    "documentation. Do not repair the candidate. Treat identity binding, "
                    "result shape, receipt cardinality, coverage accounting, and "
                    "authorization as mechanical obligations that the deterministic gate "
                    "will validate. Copy bound identities exactly and return every required "
                    "record, but spend reasoning on semantic forks, contract basis, "
                    "counterexamples, and paired causal attribution. Each regressions item must "
                    "be an object with exactly claim, contract_basis, baseline_evidence, "
                    "candidate_evidence, and severity. contract_basis must be task_source, "
                    "public_signature, public_consumer, normative_definition, or "
                    "cross_module_invariant; severity is blocking or advisory. Use blocking "
                    "only when both evidence fields are non-empty and demonstrate a "
                    "candidate-caused failure. Do not place speculative or candidate-only "
                    "risks in regressions. Return protection_assessments with exactly one "
                    "object for every proposed protected_behavior. Each object has exactly "
                    "behavior, status, basis, evidence, and counterevidence; status is "
                    "corroborated, falsified, or unresolved, and basis must match the "
                    "proposal's provenance basis. A proposed protection is defeasible and "
                    "is not part of the sealed hard contract. Explicitly compare plausible "
                    "semantic variants of named algorithms or estimators before marking one "
                    "corroborated. Return verdict accept, reject, or inconclusive; "
                    "contract_preserved; regressions; protection_assessments; and non-empty "
                    "counterevidence. When review_protocol is present, execute its stages "
                    "in order. Each review_stages item has exactly stage_id, status, and "
                    "evidence; stage_id copies the listed stage id. Return one "
                    "practice_receipts item for every listed practice. Each item has exactly "
                    "practice_id, status, evidence, and reason; practice_id copies the "
                    "listed practice id. Copy review_protocol.binding_sha256 exactly into "
                    "review_protocol_sha256. Apply every document in review_profile and bind "
                    "review_profile_sha256 exactly. Return "
                    "one profile_receipts item for every check listed by the selected profile "
                    "documents. Each item has exactly profile_id, check_id, status, evidence, "
                    "and reason; status is applied, not_applicable, or unresolved. applied "
                    "requires evidence, not_applicable requires a reason, and unresolved "
                    "blocks promotion. Bind "
                    "the exact candidate, contract "
                    "seal, and context-view identities from this assignment in the result. "
                    "Return one JSON object with generic TeamRun fields status, summary, "
                    "claims, evidence, coverage, children, and prune_proposals, plus these "
                    "top-level gate fields: verdict, candidate_artifact_identity, "
                    "contract_seal_sha256, context_view_sha256, contract_preserved, "
                    "regressions, protection_assessments, counterevidence, review_stages, "
                    "practice_receipts, profile_receipts, review_protocol_sha256, and "
                    "review_profile_sha256. "
                    "Use status completed and "
                    "coverage.complete=true only after reviewing the complete bundle."
                ),
            }
        ]
    }


def _context_bundle(context_view: dict[str, Any]) -> dict[str, Any]:
    excluded_paths = {
        str(Path(str(path)).expanduser().resolve())
        for path in context_view.get("excluded_paths") or []
    }
    entries: list[dict[str, Any]] = []
    used_bytes = 0
    truncated = False
    for item in context_view.get("included") or []:
        if not isinstance(item, dict):
            continue
        root = Path(_text(item.get("path"))).expanduser().resolve()
        paths = (
            [root]
            if root.is_file()
            else sorted(root.rglob("*"), key=lambda path: _context_path_priority(root, path))
            if root.is_dir()
            else []
        )
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            resolved = str(path.resolve())
            if resolved in excluded_paths:
                continue
            relative_parts = path.relative_to(root).parts if root.is_dir() else (path.name,)
            if any(part in CONTEXT_BUNDLE_EXCLUDED_PARTS for part in relative_parts):
                continue
            if path.name in CONTEXT_BUNDLE_EXCLUDED_NAMES:
                continue
            size = path.stat().st_size
            label = (
                str(path.relative_to(root))
                if root.is_dir()
                else path.name
            )
            entry: dict[str, Any] = {
                "source_root": str(root),
                "path": label,
                "size_bytes": size,
                "sha256": file_sha256(path),
            }
            if size > CONTEXT_BUNDLE_FILE_MAX_BYTES:
                entry["content"] = None
                entry["omission"] = "file_too_large"
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    entry["content"] = None
                    entry["omission"] = "non_text"
                    entry["safe_summary"] = {
                        "kind": "binary_digest",
                        "suffix": path.suffix.lower(),
                        "size_bytes": size,
                        "sha256": entry["sha256"],
                    }
                else:
                    encoded_size = len(content.encode("utf-8"))
                    if used_bytes + encoded_size > CONTEXT_BUNDLE_MAX_BYTES:
                        truncated = True
                        continue
                    entry["content"] = content
                    used_bytes += encoded_size
            entries.append(entry)
    return {
        "version": 1,
        "kind": "bounded_read_only_context_projection",
        "entries": entries,
        "text_bytes": used_bytes,
        "truncated": truncated,
        "source_context_view_sha256": stable_sha256(context_view),
    }


def _context_path_priority(root: Path, path: Path) -> tuple[int, str]:
    """Keep first-party evidence visible before bounded dependency material."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    lowered = {part.lower() for part in parts}
    deprioritized = bool(lowered & CONTEXT_BUNDLE_DEPRIORITIZED_PARTS) or any(
        part.lower().endswith((".dist-info", ".egg-info")) for part in parts
    )
    return (1 if deprioritized else 0, str(path))


def decide_promotion(
    *,
    seal: dict[str, Any],
    proposal: dict[str, Any],
    context_view: dict[str, Any],
    falsifier: dict[str, Any],
    artifact_root: Path,
    baseline_snapshot: dict[str, Any] | None = None,
    candidate_snapshot: dict[str, Any] | None = None,
    review_practices: dict[str, Any] | None = None,
    review_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(seal, "contract_seal")
    _require_receipt(proposal, "candidate_proposal")
    _require_receipt(context_view, "context_view")
    context = _state_context()
    raw = falsifier.get("raw") if isinstance(falsifier.get("raw"), dict) else falsifier
    producer = falsifier.get("producer") if isinstance(falsifier.get("producer"), dict) else {}
    candidate_identity = artifact_identity(artifact_root)
    current_snapshot = public_contract_snapshot(artifact_root)
    contract_sources_current = _contract_sources_match(seal)
    regressions_raw = raw.get("regressions")
    regressions = regressions_raw if isinstance(regressions_raw, list) else []
    regression_evidence_valid = isinstance(regressions_raw, list) and all(
        _regression_evidence(item) for item in regressions
    )
    blocking_regressions = [
        item
        for item in regressions
        if isinstance(item, dict) and item.get("severity") == "blocking"
    ]
    protection_assessments = (
        raw.get("protection_assessments")
        if isinstance(raw.get("protection_assessments"), list)
        else []
    )
    protection_required = bool(seal.get("baseline_snapshot_sha256"))
    protection_assessments_valid, protected_claims_corroborated = (
        _protection_assessment_state(
            proposal,
            protection_assessments,
            required=protection_required,
        )
    )
    review_protocol = (
        _review_protocol(review_practices)
        if review_practices is not None
        else None
    )
    (
        review_protocol_bound,
        review_stages_complete,
        practice_receipts_complete,
    ) = _review_receipt_state(raw, review_protocol)
    review_profile_bound = _review_profile_bound(
        raw,
        review_profile,
        seal=seal,
    )
    profile_receipts_valid, profile_practices_complete = (
        _review_profile_receipt_state(raw, review_profile)
    )
    counterevidence = raw.get("counterevidence") if isinstance(raw.get("counterevidence"), list) else []
    verdict = _text(raw.get("verdict"))
    coverage = falsifier.get("coverage") if isinstance(falsifier.get("coverage"), dict) else {}
    checks = {
        "same_run": seal.get("run_id") == proposal.get("run_id") == falsifier.get("run_id") == context["run_id"],
        "stage_bindings": (
            seal.get("node") == "contract_audit"
            and proposal.get("node") in {"solve", "revise"}
            and context["node"] == "falsify"
            and falsifier.get("node") == context["node"]
            and falsifier.get("entry_id") == context["entry_id"]
            and context_view.get("node") == context["node"]
            and context_view.get("entry_id") == context["entry_id"]
        ),
        "seal_bound": proposal.get("contract_seal_sha256") == stable_sha256(seal),
        "candidate_bound": raw.get("candidate_artifact_identity") == proposal.get("candidate_artifact_identity"),
        "candidate_fresh": candidate_identity == proposal.get("candidate_artifact_identity"),
        "baseline_snapshot_bound": _snapshot_bound(
            baseline_snapshot,
            expected_kind="baseline",
            expected_identity=seal.get("baseline_artifact_identity"),
            expected_sha256=seal.get("baseline_snapshot_sha256"),
            required=bool(seal.get("baseline_snapshot_sha256")),
        ),
        "candidate_snapshot_bound": _snapshot_bound(
            candidate_snapshot,
            expected_kind="candidate",
            expected_identity=proposal.get("candidate_artifact_identity"),
            expected_sha256=None,
            required=bool(seal.get("baseline_snapshot_sha256")),
        ),
        "independent_identity": bool(producer.get("agent_id")) and producer.get("agent_id") != proposal.get("producer", {}).get("agent_id"),
        "falsifier_role": producer.get("role") == "falsifier",
        "solver_role": proposal.get("producer", {}).get("role") == "solver",
        "falsifier_complete": falsifier.get("status") in {"completed", "terminal"} and coverage.get("complete") is True,
        "verdict_valid": verdict in VERDICTS,
        "contract_binding": raw.get("contract_seal_sha256") == stable_sha256(seal),
        "context_view_binding": raw.get("context_view_sha256") == stable_sha256(context_view),
        "context_view_role": context_view.get("consumer_role") == "falsifier",
        "context_view_fresh": _context_view_matches(context_view),
        "contract_sources_unchanged": contract_sources_current,
        "public_contract_unchanged": _public_contract_preserved(
            seal.get("public_contract_snapshot"),
            current_snapshot,
            policy=_text(seal.get("contract_policy")) or "strict_docs",
        ),
        "contract_preserved": raw.get("contract_preserved") is True,
        "counterevidence_present": bool(counterevidence),
        "regression_evidence_valid": regression_evidence_valid,
        "no_blocking_regressions": not blocking_regressions,
        "protection_assessments_valid": protection_assessments_valid,
        "protected_claims_corroborated": protected_claims_corroborated,
        "review_protocol_bound": review_protocol_bound,
        "review_stages_complete": review_stages_complete,
        "practice_receipts_complete": practice_receipts_complete,
        "review_profile_bound": review_profile_bound,
        "profile_receipts_valid": profile_receipts_valid,
        "profile_practices_complete": profile_practices_complete,
    }
    reason_codes = [name for name, passed in checks.items() if not passed]
    hard_reject = any(
        not checks[name]
        for name in (
            "same_run",
            "stage_bindings",
            "seal_bound",
            "candidate_bound",
            "baseline_snapshot_bound",
            "candidate_snapshot_bound",
            "contract_sources_unchanged",
        )
    )
    if hard_reject:
        decision = "rollback"
    elif all(checks.values()) and verdict == "accept":
        decision = "promote"
    else:
        decision = "revise"
        if blocking_regressions:
            reason_codes.append("validated_blocking_regression")
        if verdict == "reject":
            reason_codes.append("falsifier_rejected_without_hard_evidence")
        if verdict == "inconclusive":
            reason_codes.append("falsifier_inconclusive")
    return {
        "version": 1,
        "kind": "promotion_authorization",
        **context,
        "producer": {
            "agent_id": f"promotion-gate:{context['run_id']}:{context['entry_id']}",
            "role": "deterministic_gate",
        },
        "decision": decision,
        "reason_codes": sorted(set(reason_codes)),
        "checks": checks,
        "contract_seal_sha256": stable_sha256(seal),
        "proposal_sha256": stable_sha256(proposal),
        "context_view_sha256": stable_sha256(context_view),
        "baseline_artifact_identity": seal["baseline_artifact_identity"],
        "candidate_artifact_identity": proposal["candidate_artifact_identity"],
        "solver": proposal["producer"],
        "falsifier": producer,
        "falsifier_verdict": verdict,
        "blocking_regressions": blocking_regressions,
        "regressions": regressions,
        "protection_assessments": protection_assessments,
        "profile_receipts": (
            raw.get("profile_receipts")
            if isinstance(raw.get("profile_receipts"), list)
            else []
        ),
        "review_protocol_sha256": (
            review_protocol.get("binding_sha256")
            if review_protocol is not None
            else None
        ),
        "review_profile_sha256": (
            stable_sha256(review_profile) if review_profile is not None else None
        ),
        "baseline_snapshot_sha256": (
            stable_sha256(baseline_snapshot) if baseline_snapshot is not None else None
        ),
        "candidate_snapshot_sha256": (
            stable_sha256(candidate_snapshot) if candidate_snapshot is not None else None
        ),
        "created_at": _now(),
    }


def require_decision(decision: dict[str, Any], allowed: set[str]) -> None:
    _require_receipt(decision, "promotion_authorization")
    if decision.get("decision") not in allowed:
        raise ValueError(
            f"promotion decision {decision.get('decision')!r} is not allowed here; expected {sorted(allowed)}"
        )


def verify_application(
    *,
    decision: dict[str, Any],
    seal: dict[str, Any],
    artifact_root: Path,
    mode: str,
    review_route: dict[str, Any] | None = None,
    provider_application: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_receipt(decision, "promotion_authorization")
    _require_receipt(seal, "contract_seal")
    if mode == "promote":
        require_decision(decision, {"promote"})
        expected = decision["candidate_artifact_identity"]
        effective_authorization = decision
    elif mode == "quarantine":
        if review_route is None:
            raise ValueError("quarantine requires an effective review route")
        _require_effective_review_route(review_route, decision, {"quarantine"})
        effective_authorization = review_route
        expected = decision["candidate_artifact_identity"]
    else:
        if review_route is None:
            require_decision(decision, {"rollback"})
            effective_authorization = decision
        else:
            _require_effective_review_route(review_route, decision, {"rollback"})
            effective_authorization = review_route
        expected = seal["baseline_artifact_identity"]
    provider_required = bool(seal.get("baseline_snapshot_sha256"))
    if provider_application is not None:
        _require_receipt(provider_application, "filesystem_artifact_application")
        expected_mode = {
            "promote": "activate",
            "quarantine": "quarantine",
            "rollback": "restore",
        }[mode]
        if provider_application.get("mode") != expected_mode:
            raise ValueError("provider application mode does not match promotion mode")
        if not provider_application.get("verified"):
            raise ValueError("provider application is not verified")
        if provider_application.get("observed_artifact_identity") != expected:
            raise ValueError("provider application identity does not match authorization")
    elif provider_required:
        raise ValueError("provider application receipt is required")
    observed = artifact_identity(artifact_root)
    if observed != expected:
        raise ValueError(
            f"external artifact {mode} did not produce the authorized identity: expected {expected}, got {observed}"
        )
    context = _state_context()
    return {
        "version": 1,
        "kind": "artifact_application_verification",
        **context,
        "producer": {
            "agent_id": f"application-verifier:{context['run_id']}:{context['entry_id']}",
            "role": "stateful_hook",
        },
        "mode": mode,
        "authorized_decision_sha256": stable_sha256(decision),
        "effective_authorization_kind": effective_authorization["kind"],
        "effective_authorization_sha256": stable_sha256(effective_authorization),
        "expected_artifact_identity": expected,
        "observed_artifact_identity": observed,
        "artifact_provider": (
            "filesystem_snapshot_provider" if provider_application is not None else "external"
        ),
        "provider_application_sha256": (
            stable_sha256(provider_application) if provider_application is not None else None
        ),
        "verified": True,
        "created_at": _now(),
    }


def _require_effective_review_route(
    route: dict[str, Any],
    decision: dict[str, Any],
    allowed: set[str],
) -> None:
    _require_receipt(route, "recovering_develop_review_route")
    if route.get("route") not in allowed:
        raise ValueError(
            f"effective review route {route.get('route')!r} is not allowed here; "
            f"expected {sorted(allowed)}"
        )
    for field in ("run_id", "node", "entry_id"):
        if route.get(field) != decision.get(field):
            raise ValueError(f"effective review route {field} does not match promotion decision")
    if route.get("promotion_decision") != decision.get("decision"):
        raise ValueError("effective review route does not preserve the promotion decision")
    if route.get("promotion_decision_sha256") != stable_sha256(decision):
        raise ValueError("effective review route is not bound to the promotion decision")
    if route.get("route") != decision.get("decision") and not route.get(
        "review_budget_exhausted"
    ):
        raise ValueError("effective review route changed without an exhausted review budget")


def _load_current_falsifier_result() -> dict[str, Any]:
    return _load_current_role_result("falsifier")


def _load_current_role_result(role: str) -> dict[str, Any]:
    context = _state_context()
    state_path = _active_state_path(context["run_id"])
    if state_path is None:
        raise ValueError("cannot discover TeamRun result without an active StateM state file")
    node_dir = (
        state_path.parent
        / "nodes"
        / _clean(context["node"])
        / context["entry_id"]
        / "multi_agent"
    )
    results = sorted(node_dir.glob("tasks/*/results/*.json"))
    matches: list[dict[str, Any]] = []
    for path in results:
        payload = _read_json(path)
        producer = payload.get("producer") if isinstance(payload.get("producer"), dict) else {}
        if producer.get("role") == role:
            matches.append(payload)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one current {role} result, found {len(matches)}"
        )
    return matches[0]


def _state_context() -> dict[str, str]:
    run_id = _text(os.environ.get("STATEM_RUN_ID"))
    state_dir = Path(os.environ.get("STATEM_STATE_DIR") or ".statem").expanduser().resolve()
    state: dict[str, Any] = {}
    if run_id:
        for candidate in (state_dir / "runs").glob("*/state.json"):
            try:
                value = _read_json(candidate)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if value.get("run_id") == run_id:
                state = value
                break
    node = _text(state.get("current") or os.environ.get("STATEM_CURRENT"))
    entry_id = _text(state.get("current_entry_id") or os.environ.get("STATEM_ENTRY_ID"))
    context: dict[str, str] = {
        "run_id": run_id or _text(state.get("run_id")),
        "node": node,
        "entry_id": entry_id,
    }
    if not all(context.values()):
        raise ValueError("StateM run, node, and entry identity are required")
    return context


def _active_state_path(run_id: str) -> Path | None:
    state_dir = Path(os.environ.get("STATEM_STATE_DIR") or ".statem").expanduser().resolve()
    for candidate in (state_dir / "runs").glob("*/state.json"):
        try:
            value = _read_json(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if value.get("run_id") == run_id:
            return candidate
    return None


def _producer() -> dict[str, str]:
    agent_id = _text(os.environ.get("STATEM_AGENT_ID"))
    role = _text(os.environ.get("STATEM_AGENT_ROLE"))
    if not agent_id or not role:
        raise ValueError("StateM agent id and role are required")
    return {"agent_id": agent_id, "role": role}


def _contract_sources_match(seal: dict[str, Any]) -> bool:
    for source in seal.get("contract_sources") or []:
        if not isinstance(source, dict):
            return False
        path = Path(_text(source.get("path")))
        if not path.is_file() or file_sha256(path) != source.get("sha256"):
            return False
    return True


def _context_view_matches(context_view: dict[str, Any]) -> bool:
    for item in context_view.get("included") or []:
        if not isinstance(item, dict):
            return False
        path = Path(_text(item.get("path")))
        try:
            if item.get("kind") == "file":
                observed = "file-sha256:" + file_sha256(path)
            elif item.get("kind") == "directory":
                observed = artifact_identity(path)
            else:
                return False
        except (OSError, ValueError):
            return False
        if observed != item.get("identity"):
            return False
    return True


def _public_contract_preserved(
    sealed: Any,
    current: Any,
    *,
    policy: str = "strict_docs",
) -> bool:
    if not isinstance(sealed, dict) or not isinstance(current, dict):
        return False
    if policy == "repair_aware":
        for key, value in sealed.items():
            if not isinstance(value, dict):
                return False
            signature = value.get("signature")
            if signature == "module":
                continue
            current_value = current.get(key)
            if not isinstance(current_value, dict):
                return False
            if current_value.get("signature") != signature:
                return False
        return True
    if policy != "strict_docs":
        return False
    return all(current.get(key) == value for key, value in sealed.items())


def _protected_behavior_basis(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("protected_behavior_basis must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"behavior", "basis", "evidence"}:
            raise ValueError(
                "each protected_behavior_basis item must contain exactly behavior, basis, and evidence"
            )
        behavior = _text(item.get("behavior"))
        basis = _text(item.get("basis"))
        evidence = _text(item.get("evidence"))
        if not behavior or not evidence or basis not in PROVENANCE_BASES:
            raise ValueError("protected behavior provenance is missing or unsupported")
        normalized.append(
            {"behavior": behavior, "basis": basis, "evidence": evidence}
        )
    if len({item["behavior"] for item in normalized}) != len(normalized):
        raise ValueError("protected_behavior_basis contains duplicate behavior bindings")
    return normalized


def _regression_evidence(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "claim",
        "contract_basis",
        "baseline_evidence",
        "candidate_evidence",
        "severity",
    }:
        return False
    return (
        bool(_text(value.get("claim")))
        and value.get("contract_basis") in PROVENANCE_BASES
        and bool(_text(value.get("baseline_evidence")))
        and bool(_text(value.get("candidate_evidence")))
        and value.get("severity") in REGRESSION_SEVERITIES
    )


def _protection_assessment_state(
    proposal: dict[str, Any],
    assessments: list[Any],
    *,
    required: bool,
) -> tuple[bool, bool]:
    if not required and not assessments:
        return True, True
    protected = proposal.get("protected_behavior")
    bases = proposal.get("protected_behavior_basis")
    if not isinstance(protected, list) or not isinstance(bases, list):
        return False, False
    basis_by_behavior = {
        item.get("behavior"): item.get("basis")
        for item in bases
        if isinstance(item, dict)
    }
    normalized: dict[str, dict[str, Any]] = {}
    for item in assessments:
        if not isinstance(item, dict) or set(item) != {
            "behavior",
            "status",
            "basis",
            "evidence",
            "counterevidence",
        }:
            return False, False
        behavior = _text(item.get("behavior"))
        if (
            not behavior
            or behavior in normalized
            or item.get("status") not in PROTECTION_STATUSES
            or item.get("basis") != basis_by_behavior.get(behavior)
            or not _text(item.get("evidence"))
            or not _text(item.get("counterevidence"))
        ):
            return False, False
        normalized[behavior] = item
    valid = set(normalized) == set(protected)
    corroborated = valid and all(
        item.get("status") == "corroborated" for item in normalized.values()
    )
    return valid, corroborated


def _review_protocol(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("version") != 1 or catalog.get("role") != "falsifier":
        raise ValueError("review practice catalog must be version 1 for falsifier")
    stages = catalog.get("stages")
    practices = catalog.get("practices")
    if not isinstance(stages, list) or not stages:
        raise ValueError("review practice catalog requires stages")
    if not isinstance(practices, list) or not practices:
        raise ValueError("review practice catalog requires practices")
    stage_ids: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {"id", "objective"}:
            raise ValueError("review stage must contain exactly id and objective")
        stage_id = _text(stage.get("id"))
        if not stage_id or stage_id in stage_ids or not _text(stage.get("objective")):
            raise ValueError("review stage ids and objectives must be unique and non-empty")
        stage_ids.add(stage_id)
    practice_ids: set[str] = set()
    for practice in practices:
        if not isinstance(practice, dict) or set(practice) != {
            "id",
            "allow_not_applicable",
            "trigger",
            "procedure",
            "required_evidence",
        }:
            raise ValueError(
                "review practice must contain id, applicability, trigger, procedure, and evidence"
            )
        practice_id = _text(practice.get("id"))
        if (
            not practice_id
            or practice_id in practice_ids
            or not isinstance(practice.get("allow_not_applicable"), bool)
            or not _text(practice.get("trigger"))
            or not _text(practice.get("procedure"))
            or not _text(practice.get("required_evidence"))
        ):
            raise ValueError("review practices must be unique and complete")
        practice_ids.add(practice_id)
    protocol = {
        "version": 1,
        "role": "falsifier",
        "stages": stages,
        "practices": practices,
        "catalog_sha256": stable_sha256(catalog),
    }
    return {**protocol, "binding_sha256": stable_sha256(protocol)}


def _review_receipt_state(
    raw: dict[str, Any],
    protocol: dict[str, Any] | None,
) -> tuple[bool, bool, bool]:
    if protocol is None:
        return True, True, True
    protocol_bound = raw.get("review_protocol_sha256") == protocol.get(
        "binding_sha256"
    )
    stages = raw.get("review_stages")
    expected_stages = [item["id"] for item in protocol["stages"]]
    stages_complete = isinstance(stages, list) and len(stages) == len(expected_stages)
    if stages_complete:
        for expected, item in zip(expected_stages, stages):
            if (
                not isinstance(item, dict)
                or set(item) != {"stage_id", "status", "evidence"}
                or item.get("stage_id") != expected
                or item.get("status") != "completed"
                or not _text(item.get("evidence"))
            ):
                stages_complete = False
                break

    receipts = raw.get("practice_receipts")
    practices_by_id = {item["id"]: item for item in protocol["practices"]}
    receipts_complete = isinstance(receipts, list) and len(receipts) == len(
        practices_by_id
    )
    seen: set[str] = set()
    if receipts_complete:
        for item in receipts:
            if not isinstance(item, dict) or set(item) != {
                "practice_id",
                "status",
                "evidence",
                "reason",
            }:
                receipts_complete = False
                break
            practice_id = _text(item.get("practice_id"))
            practice = practices_by_id.get(practice_id)
            status = item.get("status")
            if practice is None or practice_id in seen or status == "blocked":
                receipts_complete = False
                break
            if status == "applied":
                if not _text(item.get("evidence")):
                    receipts_complete = False
                    break
            elif status == "not_applicable":
                if not practice["allow_not_applicable"] or not _text(item.get("reason")):
                    receipts_complete = False
                    break
            else:
                receipts_complete = False
                break
            seen.add(practice_id)
        receipts_complete = receipts_complete and seen == set(practices_by_id)
    return protocol_bound, stages_complete, receipts_complete


def _review_profile_catalog(
    catalog: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], int]:
    if catalog.get("version") != 1:
        raise ValueError("review profile catalog must be version 1")
    base = _text(catalog.get("base"))
    max_secondary = catalog.get("max_secondary")
    raw_profiles = catalog.get("profiles")
    if not base or not isinstance(max_secondary, int) or max_secondary < 0:
        raise ValueError("review profile catalog base and secondary budget are required")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("review profile catalog requires profiles")
    profiles: dict[str, dict[str, Any]] = {}
    for item in raw_profiles:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "file",
            "description",
            "checks",
        }:
            raise ValueError(
                "review profile entries require id, file, description, and checks"
            )
        profile_id = _text(item.get("id"))
        filename = _text(item.get("file"))
        description = _text(item.get("description"))
        checks = item.get("checks")
        if (
            not profile_id
            or profile_id in profiles
            or not filename
            or not description
            or not isinstance(checks, list)
            or not checks
            or not all(_text(check) for check in checks)
            or len(set(checks)) != len(checks)
        ):
            raise ValueError("review profile entries must be unique and complete")
        if Path(filename).name != filename:
            raise ValueError("review profile files must be catalog-relative basenames")
        profiles[profile_id] = {
            "file": filename,
            "description": description,
            "checks": checks,
        }
    return base, profiles, max_secondary


def _review_profile_receipt_state(
    raw: dict[str, Any],
    profile: dict[str, Any] | None,
) -> tuple[bool, bool]:
    if profile is None:
        return True, True
    documents = profile.get("documents")
    if not isinstance(documents, list):
        return False, False
    expected_order: list[tuple[str, str]] = []
    expected: set[tuple[str, str]] = set()
    for document in documents:
        if not isinstance(document, dict):
            return False, False
        profile_id = _text(document.get("profile_id"))
        checks = document.get("checks")
        if not profile_id or not isinstance(checks, list):
            return False, False
        for check in checks:
            check_id = _text(check)
            if not check_id or (profile_id, check_id) in expected:
                return False, False
            key = (profile_id, check_id)
            expected.add(key)
            expected_order.append(key)

    receipts = raw.get("profile_receipts")
    if not isinstance(receipts, list):
        return False, False
    seen: set[tuple[str, str]] = set()
    observed_order: list[tuple[str, str]] = []
    complete = True
    for item in receipts:
        if not isinstance(item, dict) or set(item) != {
            "profile_id",
            "check_id",
            "status",
            "evidence",
            "reason",
        }:
            return False, False
        key = (_text(item.get("profile_id")), _text(item.get("check_id")))
        status = _text(item.get("status"))
        if key not in expected or key in seen or status not in PROFILE_RECEIPT_STATUSES:
            return False, False
        if status == "applied":
            if not _text(item.get("evidence")):
                return False, False
        elif status == "not_applicable":
            if not _text(item.get("reason")):
                return False, False
        else:
            complete = False
        seen.add(key)
        observed_order.append(key)
    valid = seen == expected and observed_order == expected_order
    return valid, valid and complete


def _review_profile_bound(
    raw: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    seal: dict[str, Any],
) -> bool:
    if profile is None:
        return True
    if profile.get("version") != 1 or profile.get("kind") != "review_profile_selection":
        return False
    if profile.get("contract_seal_sha256") != stable_sha256(seal):
        return False
    return raw.get("review_profile_sha256") == stable_sha256(profile)


def _snapshot_bound(
    receipt: dict[str, Any] | None,
    *,
    expected_kind: str,
    expected_identity: Any,
    expected_sha256: Any,
    required: bool,
) -> bool:
    if receipt is None:
        return not required
    if receipt.get("version") != 1 or receipt.get("kind") != "filesystem_artifact_snapshot":
        return False
    if receipt.get("snapshot_kind") != expected_kind:
        return False
    if receipt.get("artifact_identity") != expected_identity:
        return False
    if receipt.get("snapshot_identity") != expected_identity:
        return False
    if expected_sha256 and stable_sha256(receipt) != expected_sha256:
        return False
    path = Path(_text(receipt.get("snapshot_path")))
    try:
        if not path.is_dir() or artifact_identity(path) != expected_identity:
            return False
    except (OSError, ValueError):
        return False
    return receipt.get("immutable") is True


def _require_receipt(receipt: dict[str, Any], kind: str) -> None:
    if receipt.get("version") != 1 or receipt.get("kind") != kind:
        raise ValueError(f"expected version-1 {kind} receipt")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    value = _yaml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()) or "node"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
