from __future__ import annotations

from integrations.harbor.statem_codex_thin_family_v4p72_exp import (
    ThinFamilyV4p72ExperimentalStatemCodex,
)


class ThinFamilyV4p73ExperimentalStatemCodex(
    ThinFamilyV4p72ExperimentalStatemCodex
):
    """Permit up to two precise visible-claim supplements in adapted cells."""

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p73-exp"
