from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p73_exp import (
    ThinFamilyV4p73ExperimentalStatemCodex,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG_V3 = _REPO_ROOT / "examples" / "tb3-thin-family-practices-v3.json"


def build_thin_reviewer_projection(
    selection: dict[str, Any],
    catalog_path: str | Path = _DEFAULT_CATALOG_V3,
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


class ThinFamilyV4p75ExperimentalStatemCodex(ThinFamilyV4p73ExperimentalStatemCodex):
    """Use exact adapted controls and keep detailed checks reviewer-scoped."""

    def __init__(
        self,
        *args: Any,
        development_supplement_ids: Sequence[str] | None = None,
        **kwargs: Any,
    ):
        self._development_supplement_ids = tuple(development_supplement_ids or ())
        if len(set(self._development_supplement_ids)) != len(
            self._development_supplement_ids
        ):
            raise ValueError("development supplement ids must be unique")
        if len(self._development_supplement_ids) > 2:
            raise ValueError("at most two development supplements may be selected")
        super().__init__(
            *args, practice_catalog_path=str(_DEFAULT_CATALOG_V3), **kwargs
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p75-exp"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if self._development_practice_id is None:
            await super().run(instruction, environment, context)
            return

        selection = select_thin_family_practice(
            instruction,
            self._practice_catalog_path,
            activation_mode=self._activation_mode,
        )
        if selection.get("practice_id") != self._development_practice_id:
            raise RuntimeError("adapted practice mismatch")
        available = {
            item.get("supplement_id") for item in selection.get("supplements", [])
        }
        requested = set(self._development_supplement_ids)
        missing = sorted(requested - available)
        if missing:
            raise RuntimeError("adapted supplement mismatch: " + ", ".join(missing))

        self._thin_family_selection = copy.deepcopy(selection)
        self._thin_family_selection.update(
            {
                "activated": True,
                "activation_reason": "explicit_adapted_development",
                "development_override": True,
                "exact_development_supplement_ids": sorted(requested),
            }
        )
        for supplement in self._thin_family_selection.get("supplements", []):
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
        await StatemCodex.run(self, instruction, environment, context)
