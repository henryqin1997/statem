from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Sequence

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from statem.miniyaml import loads as load_runbook

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p73_exp import (
    ThinFamilyV4p73ExperimentalStatemCodex,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG_V4 = _REPO_ROOT / "examples" / "tb3-thin-family-practices-v4.json"
_REMOTE_PHASED_RUNBOOK = PurePosixPath("/tmp/statem-runbooks/coding-agent-phased.json")


def build_thin_reviewer_projection(
    selection: dict[str, Any],
    catalog_path: str | Path = _DEFAULT_CATALOG_V4,
) -> dict[str, Any]:
    """Load detailed checks for an invoked reviewer without exposing them to solve."""

    if not selection.get("activated"):
        raise ValueError("reviewer projection requires an activated practice")
    path = Path(catalog_path).resolve()
    catalog_bytes = path.read_bytes()
    catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
    if selection.get("catalog_sha256") != catalog_sha256:
        raise ValueError("reviewer projection catalog identity mismatch")
    data = json.loads(catalog_bytes)
    policy = data.get("selection_policy") or {}
    if policy.get("solver_projection") != "compact_only":
        raise ValueError("catalog solver projection is not compact-only")
    if policy.get("reviewer_projection") != "detailed_only_when_invoked":
        raise ValueError("catalog reviewer projection is not invocation-scoped")

    practices = {item["practice_id"]: item for item in data.get("practices", [])}
    practice = practices.get(selection.get("practice_id"))
    if practice is None:
        raise ValueError("reviewer projection practice is absent from catalog")
    detailed = practice.get("detailed")
    if not isinstance(detailed, dict) or detailed.get("reviewer_only") is not True:
        raise ValueError("reviewer projection requires reviewer-only detail")
    expected_detail = hashlib.sha256(
        json.dumps(detailed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if selection.get("detailed_sha256") != expected_detail:
        raise ValueError("reviewer projection detailed identity mismatch")

    supplements = {item["supplement_id"]: item for item in data.get("supplements", [])}
    selected_supplements = []
    for selected in selection.get("supplements", []):
        if not selected.get("activated"):
            continue
        supplement = supplements.get(selected.get("supplement_id"))
        if supplement is None:
            raise ValueError("reviewer supplement is absent from catalog")
        supplement_detail = supplement.get("detailed")
        if (
            not isinstance(supplement_detail, dict)
            or supplement_detail.get("reviewer_only") is not True
        ):
            raise ValueError("reviewer supplement detail must be reviewer-only")
        selected_supplements.append(
            {
                "supplement_id": supplement["supplement_id"],
                "detailed": supplement_detail,
            }
        )
    return {
        "version": 1,
        "kind": "tb3_thin_reviewer_projection",
        "catalog_sha256": catalog_sha256,
        "family": selection["family"],
        "practice_id": selection["practice_id"],
        "detailed": detailed,
        "supplements": selected_supplements,
    }


def build_solver_projection(
    selection: dict[str, Any],
    phase: str,
    catalog_path: str | Path = _DEFAULT_CATALOG_V4,
) -> dict[str, Any]:
    """Project only obligations that can change the current phase decision."""

    if phase not in {"pre_solve", "verify"}:
        raise ValueError("phase must be pre_solve or verify")
    if not selection.get("activated"):
        raise ValueError("solver projection requires an activated practice")
    path = Path(catalog_path).resolve()
    catalog_bytes = path.read_bytes()
    catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
    if selection.get("catalog_sha256") != catalog_sha256:
        raise ValueError("solver projection catalog identity mismatch")
    data = json.loads(catalog_bytes)
    policy = data.get("selection_policy") or {}
    if policy.get("phase_projection") != "pre_solve_then_verify":
        raise ValueError("catalog does not enable phased projection")

    practices = {item["practice_id"]: item for item in data.get("practices", [])}
    practice = practices.get(selection.get("practice_id"))
    if practice is None:
        raise ValueError("solver projection practice is absent from catalog")
    supplements = {item["supplement_id"]: item for item in data.get("supplements", [])}
    selected_items = [practice]
    for selected in selection.get("supplements", []):
        if not selected.get("activated"):
            continue
        supplement = supplements.get(selected.get("supplement_id"))
        if supplement is None:
            raise ValueError("solver projection supplement is absent from catalog")
        selected_items.append(supplement)

    field = "direction_cues" if phase == "pre_solve" else "verify_obligations"
    budget_field = (
        "pre_solve_char_budget" if phase == "pre_solve" else "verify_char_budget"
    )
    obligations: list[str] = []
    for item in selected_items:
        values = (item.get("compact") or {}).get(field)
        if not isinstance(values, list) or not values:
            raise ValueError(f"{field} must be a non-empty list")
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} entries must be non-empty strings")
            normalized = value.strip()
            if normalized not in obligations:
                obligations.append(normalized)
    char_budget = policy.get(budget_field)
    if not isinstance(char_budget, int) or char_budget <= 0:
        raise ValueError(f"{budget_field} must be a positive integer")
    char_count = sum(len(item) for item in obligations)
    if char_count > char_budget:
        raise ValueError(f"{phase} projection exceeds its character budget")
    return {
        "version": 1,
        "kind": "tb3_thin_solver_projection",
        "phase": phase,
        "catalog_sha256": catalog_sha256,
        "family": selection["family"],
        "practice_id": selection["practice_id"],
        "obligations": obligations,
        "char_count": char_count,
        "char_budget": char_budget,
        "stop_rule": (practice.get("compact") or {}).get("stop_rule")
        if phase == "verify"
        else None,
    }


def build_phased_runbook_overlay(
    runbook_path: str | Path,
    selection: dict[str, Any],
    catalog_path: str | Path = _DEFAULT_CATALOG_V4,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append late obligations to verify without adding states or edges."""

    path = Path(runbook_path).resolve()
    base_bytes = path.read_bytes()
    rendered = copy.deepcopy(load_runbook(base_bytes.decode("utf-8")))
    nodes = rendered.get("nodes")
    if not isinstance(nodes, dict) or not isinstance(nodes.get("verify"), dict):
        raise ValueError("thin runbook must contain a verify node")
    verify_prompt = nodes["verify"].get("prompt")
    if not isinstance(verify_prompt, str) or not verify_prompt.strip():
        raise ValueError("thin runbook verify prompt is absent")
    projection = build_solver_projection(selection, "verify", catalog_path)
    obligations = "\n".join(
        f"- {obligation}" for obligation in projection["obligations"]
    )
    nodes["verify"]["prompt"] = (
        verify_prompt.rstrip()
        + "\n\nConditionally selected late family verification:\n"
        + f"- family: {projection['family']}\n"
        + f"- practice_id: {projection['practice_id']}\n"
        + obligations
        + "\n- stop_rule: "
        + str(projection["stop_rule"])
        + "\nDetailed reviewer checks remain outside the task runbook."
    )
    rendered_bytes = json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    receipt = {
        "version": 1,
        "kind": "tb3_phased_runbook_overlay",
        "base_runbook_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "catalog_sha256": projection["catalog_sha256"],
        "family": projection["family"],
        "practice_id": projection["practice_id"],
        "verify_projection_sha256": hashlib.sha256(
            json.dumps(projection, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "rendered_runbook_sha256": hashlib.sha256(rendered_bytes).hexdigest(),
        "nodes": sorted(nodes),
        "edge_count": len(rendered.get("edges") or []),
    }
    return rendered, receipt


class ThinFamilyV4p76ExperimentalStatemCodex(ThinFamilyV4p73ExperimentalStatemCodex):
    """Project direction before solve and acceptance obligations at verify."""

    def __init__(
        self,
        *args: Any,
        development_supplement_ids: Sequence[str] | None = None,
        practice_catalog_path: str | None = None,
        **kwargs: Any,
    ):
        self._development_supplement_ids = tuple(development_supplement_ids or ())
        if len(set(self._development_supplement_ids)) != len(
            self._development_supplement_ids
        ):
            raise ValueError("development supplement ids must be unique")
        if len(self._development_supplement_ids) > 2:
            raise ValueError("at most two development supplements may be selected")
        self._phased_runbook_receipt: dict[str, Any] | None = None
        self._use_phased_runbook = False
        super().__init__(
            *args,
            practice_catalog_path=str(
                practice_catalog_path or _DEFAULT_CATALOG_V4
            ),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p76-exp"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        selection = select_thin_family_practice(
            instruction,
            self._practice_catalog_path,
            activation_mode=self._activation_mode,
        )
        if self._development_practice_id is not None:
            if selection.get("practice_id") != self._development_practice_id:
                raise RuntimeError("adapted practice mismatch")
            available = {
                item.get("supplement_id") for item in selection.get("supplements", [])
            }
            requested = set(self._development_supplement_ids)
            missing = sorted(requested - available)
            if missing:
                raise RuntimeError("adapted supplement mismatch: " + ", ".join(missing))
            selection = copy.deepcopy(selection)
            selection.update(
                {
                    "activated": True,
                    "activation_reason": "explicit_adapted_development",
                    "development_override": True,
                    "exact_development_supplement_ids": sorted(requested),
                }
            )
            for supplement in selection.get("supplements", []):
                supplement_id = supplement.get("supplement_id")
                supplement.update(
                    {
                        "activated": supplement_id in requested,
                        "activation_reason": (
                            "explicit_adapted_development"
                            if supplement_id in requested
                            else "not_selected_for_causal_cell"
                        ),
                    }
                )
        self._thin_family_selection = selection
        if not selection.get("activated"):
            await self._run_native_direct(instruction, environment, context)
            return

        rendered, receipt = build_phased_runbook_overlay(
            self._runbook_path,
            selection,
            self._practice_catalog_path,
        )
        await self._write_remote_text(
            environment,
            _REMOTE_PHASED_RUNBOOK.as_posix(),
            json.dumps(rendered, indent=2, sort_keys=True) + "\n",
        )
        validation = await self.exec_as_agent(
            environment,
            command=(
                f"statem validate {_REMOTE_PHASED_RUNBOOK.as_posix()} --strict --json"
            ),
            env=self._statem_env(self._run_id(environment)),
        )
        return_code = getattr(
            validation,
            "return_code",
            getattr(validation, "returncode", 0),
        )
        if return_code not in (None, 0):
            raise RuntimeError("phased task runbook failed strict validation")
        self._phased_runbook_receipt = receipt
        self._use_phased_runbook = True
        await StatemCodex.run(self, instruction, environment, context)

    def _remote_runbook_for_instruction(self, instruction: str) -> PurePosixPath:
        if self._use_phased_runbook:
            return _REMOTE_PHASED_RUNBOOK
        return super()._remote_runbook_for_instruction(instruction)

    def _augment_instruction(
        self,
        instruction: str,
        run_id: str,
        current_context: str,
    ) -> str:
        base = StatemCodex._augment_instruction(
            self, instruction, run_id, current_context
        )
        selection = self._thin_family_selection
        if not selection or not selection.get("activated"):
            return base
        projection = build_solver_projection(
            selection, "pre_solve", self._practice_catalog_path
        )
        cues = "\n".join(f"- {cue}" for cue in projection["obligations"])
        return (
            base
            + "\n\nConditionally selected pre-solve family direction:\n"
            + f"- family: {projection['family']}\n"
            + f"- practice_id: {projection['practice_id']}\n"
            + cues
            + "\nLate acceptance checks are state-scoped to verify. Detailed "
            + "reviewer checks are not in solver context."
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
        if self._phased_runbook_receipt is not None:
            statem_metadata["phased_runbook"] = self._phased_runbook_receipt
        context.metadata["statem"] = statem_metadata
