from __future__ import annotations

from integrations.harbor.statem_codex_thin_family_v4p71_exp import (
    ThinFamilyV4p71ExperimentalStatemCodex,
)


class ThinFamilyV4p72ExperimentalStatemCodex(
    ThinFamilyV4p71ExperimentalStatemCodex
):
    """Add at most one visible-claim compact supplement in adapted cells."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p72-exp"
