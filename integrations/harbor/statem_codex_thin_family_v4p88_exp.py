from __future__ import annotations

from pathlib import Path
from typing import Any

from integrations.harbor.statem_codex_thin_family_v4p77_exp import (
    ThinFamilyV4p77ExperimentalStatemCodex,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG_V6 = _REPO_ROOT / "examples" / "tb3-thin-family-practices-v6.json"


class ThinFamilyV4p88ExperimentalStatemCodex(
    ThinFamilyV4p77ExperimentalStatemCodex
):
    """Use the versioned biological artifact-consistency practice catalog."""

    def __init__(
        self,
        *args: Any,
        practice_catalog_path: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            *args,
            practice_catalog_path=str(
                practice_catalog_path or _DEFAULT_CATALOG_V6
            ),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p88-exp"
