from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from integrations.harbor.statem_codex import ThinStatemCodex


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG = _REPO_ROOT / "examples" / "tb3-thin-family-practices-v1.json"


def select_thin_family_practice(
    instruction: str,
    catalog_path: str | Path = _DEFAULT_CATALOG,
    *,
    activation_mode: str = "shadow",
) -> dict[str, Any]:
    if activation_mode not in {"shadow", "active"}:
        raise ValueError("activation_mode must be shadow or active")
    path = Path(catalog_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("thin family catalog must use version 1")
    if data.get("selection_policy", {}).get("max_selected") != 1:
        raise ValueError("thin family catalog must select at most one practice")

    matches: list[dict[str, Any]] = []
    for practice in data.get("practices", []):
        groups = practice.get("trigger_groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"practice {practice.get('practice_id')!r} has no trigger groups")
        matched_patterns: list[str] = []
        matched = True
        for group in groups:
            if not isinstance(group, list) or not group:
                raise ValueError(
                    f"practice {practice.get('practice_id')!r} has an empty trigger group"
                )
            group_match = next(
                (
                    str(pattern)
                    for pattern in group
                    if re.search(str(pattern), instruction, flags=re.IGNORECASE)
                ),
                None,
            )
            if group_match is None:
                matched = False
                break
            matched_patterns.append(group_match)
        if matched:
            matches.append(
                {
                    "priority": int(practice.get("priority") or 1000),
                    "practice": practice,
                    "matched_patterns": matched_patterns,
                }
            )

    matches.sort(
        key=lambda item: (
            item["priority"],
            str(item["practice"].get("practice_id") or ""),
        )
    )
    selected = matches[0] if matches else None
    selected_admitted = bool(
        selected
        and selected["practice"].get("validation", {}).get("admitted")
    )
    catalog_bytes = path.read_bytes()
    receipt: dict[str, Any] = {
        "version": 1,
        "kind": "tb3_thin_family_selection",
        "activation_mode": activation_mode,
        "source": "visible_instruction_only",
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "catalog_version": data["version"],
        "selected": selected is not None,
        "activated": (
            selected is not None
            and selected_admitted
            and activation_mode == "active"
        ),
        "eligible_match_count": len(matches),
        "activation_reason": (
            "no_match"
            if selected is None
            else "unadmitted_shadow"
            if not selected_admitted
            else "shadow_mode"
            if activation_mode == "shadow"
            else "admitted_active"
        ),
    }
    if selected is not None:
        practice = selected["practice"]
        receipt.update(
            {
                "practice_id": practice["practice_id"],
                "family": practice["family"],
                "trigger_evidence": selected["matched_patterns"],
                "compact": practice["compact"],
                "detailed_sha256": hashlib.sha256(
                    json.dumps(
                        practice["detailed"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "maturity": practice.get("validation", {}).get("maturity"),
                "admitted": bool(practice.get("validation", {}).get("admitted")),
            }
        )
    return receipt


class ThinFamilyV4p62ExperimentalStatemCodex(ThinStatemCodex):
    """Thin TB3 controller with at most one public-signal family practice."""

    _REMOTE_PRACTICE_CATALOG = PurePosixPath(
        "/tmp/statem-verification-checks/tb3-thin-family-practices-v1.json"
    )

    def __init__(
        self,
        *args: Any,
        runbook_path: str | None = None,
        practice_catalog_path: str | None = None,
        activation_mode: str = "shadow",
        **kwargs: Any,
    ):
        if activation_mode not in {"shadow", "active"}:
            raise ValueError("activation_mode must be shadow or active")
        runbook = _REPO_ROOT / "examples" / "terminal-bench-agent-thin-v4p62-exp.yaml"
        self._practice_catalog_path = Path(
            practice_catalog_path or _DEFAULT_CATALOG
        ).resolve()
        self._activation_mode = activation_mode
        self._thin_family_selection: dict[str, Any] | None = None
        super().__init__(
            *args,
            runbook_path=runbook_path or str(runbook),
            run_id_prefix="tb3-thin-family-v4p62",
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p62-exp"

    def _extra_source_manifest_entries(self) -> list[dict[str, Any]]:
        entries = super()._extra_source_manifest_entries()
        entries.append(
            self._manifest_entry(
                "practice_catalog",
                self._practice_catalog_path,
                self._REMOTE_PRACTICE_CATALOG,
            )
        )
        return entries

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._thin_family_selection = select_thin_family_practice(
            instruction,
            self._practice_catalog_path,
            activation_mode=self._activation_mode,
        )
        await super().run(instruction, environment, context)

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        base = super()._augment_instruction(instruction, run_id, current_context)
        selection = self._thin_family_selection or select_thin_family_practice(
            instruction,
            self._practice_catalog_path,
            activation_mode=self._activation_mode,
        )
        if not selection.get("activated"):
            return base
        compact = selection["compact"]
        obligations = "\n".join(
            f"- {obligation}" for obligation in compact["obligations"]
        )
        return (
            base
            + "\n\nConditionally selected compact family practice:\n"
            + f"- family: {selection['family']}\n"
            + f"- practice_id: {selection['practice_id']}\n"
            + obligations
            + "\n- stop_rule: "
            + str(compact["stop_rule"])
            + "\nDetailed reviewer checks are not in solver context. Do not load another "
            + "family or expand the practice catalog.\n"
        )

    async def _collect_statem_artifacts(
        self,
        environment: BaseEnvironment,
        context: AgentContext,
        run_id: str,
    ) -> None:
        await super()._collect_statem_artifacts(environment, context, run_id)
        context.metadata = dict(context.metadata or {})
        statem_metadata = dict(context.metadata.get("statem") or {})
        if self._thin_family_selection is not None:
            statem_metadata["thin_family_selection"] = self._thin_family_selection
        context.metadata["statem"] = statem_metadata
