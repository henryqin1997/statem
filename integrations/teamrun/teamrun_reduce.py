#!/usr/bin/env python3
"""Reduce a statem TeamRun reducer-input bundle into a decision JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    decision = reduce_payload(
        payload,
        strategy=args.strategy,
        candidate_field=args.candidate_field,
        confidence_field=args.confidence_field,
        require_complete_coverage=args.require_complete_coverage,
    )
    text = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if decision.get("status") != "blocked" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reduce TeamRun claims into a decision JSON.")
    parser.add_argument("--input", required=True, help="reducer-input.json from statem team reduce-input")
    parser.add_argument("--output", help="decision JSON output path; stdout when omitted")
    parser.add_argument(
        "--strategy",
        choices=["earliest-candidate", "highest-confidence", "all-claims-table", "coverage-required"],
        default="all-claims-table",
    )
    parser.add_argument("--candidate-field", default="candidate_frame")
    parser.add_argument("--confidence-field", default="confidence")
    parser.add_argument("--require-complete-coverage", action="store_true")
    return parser


def reduce_payload(
    payload: dict[str, Any],
    *,
    strategy: str,
    candidate_field: str = "candidate_frame",
    confidence_field: str = "confidence",
    require_complete_coverage: bool = False,
) -> dict[str, Any]:
    claims = _claims(payload)
    coverage = _coverage(payload)
    if require_complete_coverage or strategy == "coverage-required":
        coverage_decision = {
            "strategy": "coverage-required",
            "status": "decided" if coverage["complete"] else "blocked",
            "answer": "coverage complete" if coverage["complete"] else "coverage gaps remain",
            "coverage": coverage,
            "claims_count": len(claims),
            "evidence_refs": _evidence_refs(claims),
            "source": _source(payload),
        }
        if strategy == "coverage-required" or coverage_decision["status"] == "blocked":
            return coverage_decision
    if strategy == "earliest-candidate":
        return _candidate_decision(payload, claims, coverage, candidate_field, confidence_field, earliest=True)
    if strategy == "highest-confidence":
        return _candidate_decision(payload, claims, coverage, candidate_field, confidence_field, earliest=False)
    return {
        "strategy": "all-claims-table",
        "status": "decided" if claims else "blocked",
        "answer": f"{len(claims)} claim(s) collected",
        "coverage": coverage,
        "claims": claims,
        "evidence_refs": _evidence_refs(claims),
        "source": _source(payload),
    }


def _claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for task_entry in payload.get("tasks", []):
        task = task_entry.get("task") or {}
        task_id = str(task.get("task_id") or "")
        entries: list[tuple[str, dict[str, Any]]] = []
        entries.extend(("report", report) for report in task_entry.get("reports", []))
        entries.extend(("result", result) for result in task_entry.get("results", []))
        for source_kind, result in entries:
            producer = result.get("producer") if isinstance(result.get("producer"), dict) else {}
            result_path = str(result.get("path") or (task.get("result_path") if source_kind == "result" else "") or "")
            for index, raw_claim in enumerate(result.get("claims") or []):
                claim = dict(raw_claim) if isinstance(raw_claim, dict) else {"claim": raw_claim}
                claim["_task_id"] = task_id
                claim["_claim_index"] = index
                claim["_result_path"] = result_path
                claim["_agent_id"] = producer.get("agent_id")
                claim["_source"] = source_kind
                extracted.append(claim)
    return extracted


def _coverage(payload: dict[str, Any]) -> dict[str, Any]:
    total = 0
    complete = 0
    incomplete_tasks: list[str] = []
    open_tasks: list[str] = []
    failed_tasks: list[str] = []
    for task_entry in payload.get("tasks", []):
        total += 1
        task = task_entry.get("task") or {}
        task_id = str(task.get("task_id") or "")
        status = str(task.get("status") or "")
        if status in {"open", "leased"}:
            open_tasks.append(task_id)
        if status in {"failed", "blocked", "partial"}:
            failed_tasks.append(task_id)
        result_coverages = [
            result.get("coverage") for result in task_entry.get("results", []) if isinstance(result.get("coverage"), dict)
        ]
        task_complete = bool(result_coverages) and all(bool(coverage.get("complete")) for coverage in result_coverages)
        if task_complete or status == "pruned":
            complete += 1
        else:
            incomplete_tasks.append(task_id)
    return {
        "total_tasks": total,
        "complete_or_pruned_tasks": complete,
        "incomplete_tasks": incomplete_tasks,
        "open_tasks": open_tasks,
        "failed_tasks": failed_tasks,
        "complete": not incomplete_tasks and not open_tasks and not failed_tasks,
    }


def _candidate_decision(
    payload: dict[str, Any],
    claims: list[dict[str, Any]],
    coverage: dict[str, Any],
    candidate_field: str,
    confidence_field: str,
    *,
    earliest: bool,
) -> dict[str, Any]:
    strategy = "earliest-candidate" if earliest else "highest-confidence"
    candidates = [claim for claim in claims if _number(claim.get(candidate_field)) is not None]
    if not candidates:
        return {
            "strategy": strategy,
            "status": "blocked",
            "answer": f"no claims contained {candidate_field}",
            "coverage": coverage,
            "candidates": [],
            "source": _source(payload),
        }
    if earliest:
        selected = min(candidates, key=lambda claim: (_number(claim.get(candidate_field)), -(_number(claim.get(confidence_field)) or 0)))
    else:
        selected = max(candidates, key=lambda claim: (_number(claim.get(confidence_field)) or 0, -(_number(claim.get(candidate_field)) or 0)))
    return {
        "strategy": strategy,
        "status": "decided",
        "answer": {
            candidate_field: selected.get(candidate_field),
            confidence_field: selected.get(confidence_field),
            "task_id": selected.get("_task_id"),
            "claim": selected.get("claim") or selected.get("text") or selected,
        },
        "selected_claim": selected,
        "coverage": coverage,
        "candidates": _candidate_rows(candidates, candidate_field, confidence_field),
        "evidence_refs": _evidence_refs([selected]),
        "source": _source(payload),
    }


def _candidate_rows(claims: list[dict[str, Any]], candidate_field: str, confidence_field: str) -> list[dict[str, Any]]:
    return [
        {
            "task_id": claim.get("_task_id"),
            "agent_id": claim.get("_agent_id"),
            candidate_field: claim.get(candidate_field),
            confidence_field: claim.get(confidence_field),
            "claim": claim.get("claim") or claim.get("text"),
            "evidence_refs": claim.get("evidence_refs", []),
            "result_path": claim.get("_result_path"),
            "source": claim.get("_source"),
        }
        for claim in claims
    ]


def _evidence_refs(claims: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for claim in claims:
        for ref in claim.get("evidence_refs") or []:
            if str(ref) not in refs:
                refs.append(str(ref))
        result_path = claim.get("_result_path")
        if result_path and str(result_path) not in refs:
            refs.append(str(result_path))
    return refs


def _source(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload.get("run_id"),
        "node": payload.get("node"),
        "entry_id": payload.get("entry_id"),
        "generated_at": payload.get("generated_at"),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
