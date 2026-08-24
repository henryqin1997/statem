from __future__ import annotations

import copy
from typing import Any

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from integrations.harbor.statem_codex import StatemCodex
from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p70_exp import (
    ThinFamilyV4p70ExperimentalStatemCodex,
)


class ThinFamilyV4p71ExperimentalStatemCodex(
    ThinFamilyV4p70ExperimentalStatemCodex
):
    """Allow one explicit unadmitted practice in an adapted development cell."""

    def __init__(
        self,
        *args: Any,
        development_practice_id: str | None = None,
        **kwargs: Any,
    ):
        self._development_practice_id = development_practice_id
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p71-exp"

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
        selected_id = selection.get("practice_id")
        if selected_id != self._development_practice_id:
            raise RuntimeError(
                "adapted practice mismatch: expected "
                f"{self._development_practice_id!r}, selected {selected_id!r}"
            )

        self._thin_family_selection = copy.deepcopy(selection)
        self._thin_family_selection.update(
            {
                "activated": True,
                "activation_reason": "explicit_adapted_development",
                "development_override": True,
            }
        )
        for supplement in self._thin_family_selection.get("supplements", []):
            supplement.update(
                {
                    "activated": True,
                    "activation_reason": "explicit_adapted_development",
                }
            )
        await StatemCodex.run(self, instruction, environment, context)
